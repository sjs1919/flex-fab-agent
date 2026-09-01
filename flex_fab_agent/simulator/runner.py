"""runner.py 模拟器心跳线程（M3 T3.6）。

独立线程主循环：每 tick 单事务（transaction()）内推进 sim 时钟 + A/B 层；
tick 失败整体回滚并记录日志，心跳继续。R-3 每 tick bump llm_cache
scene_version 使状态相关精确缓存失效；D2 用独立 Tracer 实例（全局 tracer
非线程安全），span `simulator:tick`（attrs: sim_time/event_count/duration_ms）。

SIM_TICK_SECONDS 环境变量控制心跳间隔（默认 60s = 1 sim 小时；测试用
0.02 等小值加速）。
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import timedelta

from flex_fab_agent.cache.manager import cache_manager
from flex_fab_agent.config import SIM_TICK_SECONDS
from flex_fab_agent.observability import dashboard
from flex_fab_agent.observability.tracer import Tracer
from flex_fab_agent.simulator import clock, engine
from flex_fab_agent.tools.data import transaction
from flex_fab_agent.tools.scheduler_tools import kpi_metrics

logger = logging.getLogger(__name__)

# 连续失败熔断：handler 持续抛错（脏数据等）会每拍重试同一事件卡死模拟器，
# 超过该次数停止心跳线程（事件仍 scheduled，修复数据后可重启）。
MAX_CONSECUTIVE_FAILURES = 10


class SimulatorRunner:
    """模拟器心跳：start() 起线程，stop() 优雅停止。"""

    def __init__(self, tick_seconds: float | None = None) -> None:
        self.tick_seconds = (tick_seconds if tick_seconds is not None
                             else SIM_TICK_SECONDS)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._tracer = Tracer()  # D2：线程私有，不碰全局 tracer
        self.tick_count = 0
        self.consecutive_failures = 0
        self._tick_lock = threading.Lock()  # 2026-08-30 防重入：上一拍未完成则取消本次

    def run_tick(self) -> dict | None:
        """单 tick：一个事务内时钟 +1h + A/B 层推进；事务外 bump 版本 + 记 span。

        事务内任一步失败 -> 整体回滚（时钟/批次/日志无半写）后向上抛。
        防重入（2026-08-30）：上一拍推进未完成时取消本次，返回 None 不推进。
        """
        if not self._tick_lock.acquire(blocking=False):
            logger.warning("模拟器 tick 取消：上一拍推进未完成，跳过本次")
            return None
        try:
            t0 = time.perf_counter()
            with transaction() as conn:
                with conn.cursor() as cur:
                    clock.advance_sim_time(cur, 1)
                sim_time = clock.get_sim_time(conn)
                stats = engine.advance_tick(conn, sim_time)
                # 事件兜底重排（2026-08-27）：本 tick 发生设备故障/新插单/延期告警 → 即时重排信号
                if self._need_reschedule(conn, sim_time):
                    from ..scheduler.auto_scheduler import get_scheduler  # 函数内导入避免加载期循环
                    get_scheduler().request_rerun()
            self.tick_count += 1
            self.consecutive_failures = 0
            cache_manager.bump_scene_version()  # R-3：状态相关缓存失效
            cache_manager.clear_state_entries()  # tick 后订单/设备状态变化，状态类语义缓存主动失效
            self._record_kpi_snapshot(sim_time)
            # 操作日志（旁路）：事务已提交，本 tick 有事件 fired 才落，避免心跳噪音；
            # 与 _record_kpi_snapshot 同层——若前置 _need_reschedule 抛错已回滚，
            # 不会出现「未提交却落 ok」的矛盾记录
            events_fired = stats.get("events_fired", 0)
            if events_fired > 0:
                from ..observability.operation_log import record_operation
                record_operation(
                    "simulator", "模拟器tick", "ok",
                    summary=f"推进1h 事件{events_fired}条",
                    sim_time=sim_time)
            duration_ms = round((time.perf_counter() - t0) * 1000, 1)
            self._tracer.record(
                "simulator:tick", duration_ms,
                sim_time=sim_time.strftime("%Y-%m-%d %H:%M:%S"),
                event_count=stats.get("events_fired", 0),
            )
            return stats
        finally:
            self._tick_lock.release()

    def _need_reschedule(self, conn, sim_time) -> bool:
        """本 tick 是否发生需重排的事件：设备故障 fired / 新插单。

        sim_events.sim_time 为事件预排到达时刻（带秒），tick 为整点——用
        (上一 tick, 当前 tick] 窗口匹配本 tick 内新 fired 的事件。
        延期告警（硬性不可行）已由 engine 落为 fired 的 machine_failure 事件
        （payload.type=reschedule_alert），故按 event_type 查询即覆盖。
        """
        prev = sim_time - timedelta(hours=1)  # tick 每次 +1h（clock.advance_sim_time）
        with conn.cursor() as cur:
            cur.execute(
                "SELECT event_type, COUNT(*) FROM sim_events "
                "WHERE status='fired' AND event_type IN ('machine_failure','new_order') "
                "AND sim_time > %s AND sim_time <= %s GROUP BY event_type",
                (prev, sim_time))
            return bool(cur.fetchall())

    def _record_kpi_snapshot(self, sim_time) -> None:
        """事务提交后落一条 KPI 快照（M5b T5b.5，看板历史数据源）。

        快照失败只告警不熔断 tick（看板历史是旁路观测，不能拖垮模拟主链路）。
        dashboard/kpi_metrics 在模块顶部导入：daemon 线程内懒加载重组件
        （scheduler_tools -> pandas）会被主线程自旋等待抢 GIL 饿死。
        """
        try:
            dashboard.record_kpi_snapshot(kpi_metrics(), sim_time)
        except Exception:
            logger.warning("KPI 快照落库失败（tick 不中断）", exc_info=True)

    def start(self) -> None:
        """启动心跳线程（重复调用幂等：已活着直接返回）。"""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop, name="simulator", daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.run_tick()
            except Exception:
                # 单 tick 失败已整体回滚（无半写），记录后继续下一拍；
                # 连续失败达熔断阈值则停止心跳（避免脏数据导致无限重试刷日志）
                self.consecutive_failures += 1
                logger.exception("simulator tick 失败（已回滚），连续 %d 次",
                                 self.consecutive_failures)
                from ..observability.operation_log import record_operation
                record_operation(
                    "simulator", "模拟器tick", "fail",
                    summary=f"tick 异常（连续 {self.consecutive_failures} 次）")
                if self.consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    record_operation(
                        "simulator", "模拟器熔断", "fail",
                        summary=f"连续 {MAX_CONSECUTIVE_FAILURES} 拍失败，心跳停止")
                    logger.error("连续 %d 拍失败，模拟器心跳熔断停止",
                                 self.consecutive_failures)
                    return
            self._stop_event.wait(self.tick_seconds)

    def stop(self, timeout: float = 10.0) -> None:
        """停止心跳线程并等待退出。"""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()
