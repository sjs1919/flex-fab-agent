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

from demo.cache.manager import cache_manager
from demo.config import SIM_TICK_SECONDS
from demo.observability import dashboard
from demo.observability.tracer import Tracer
from demo.simulator import clock, engine
from demo.tools.data import transaction
from demo.tools.scheduler_tools import kpi_metrics

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

    def run_tick(self) -> dict:
        """单 tick：一个事务内时钟 +1h + A/B 层推进；事务外 bump 版本 + 记 span。

        事务内任一步失败 -> 整体回滚（时钟/批次/日志无半写）后向上抛。
        """
        t0 = time.perf_counter()
        with transaction() as conn:
            with conn.cursor() as cur:
                clock.advance_sim_time(cur, 1)
            sim_time = clock.get_sim_time(conn)
            stats = engine.advance_tick(conn, sim_time)
        self.tick_count += 1
        self.consecutive_failures = 0
        cache_manager.bump_scene_version()  # R-3：状态相关缓存失效
        cache_manager.clear_state_entries()  # tick 后订单/设备状态变化，状态类语义缓存主动失效
        self._record_kpi_snapshot(sim_time)
        duration_ms = round((time.perf_counter() - t0) * 1000, 1)
        self._tracer.record(
            "simulator:tick", duration_ms,
            sim_time=sim_time.strftime("%Y-%m-%d %H:%M:%S"),
            event_count=stats.get("events_fired", 0),
        )
        return stats

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
                if self.consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
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
