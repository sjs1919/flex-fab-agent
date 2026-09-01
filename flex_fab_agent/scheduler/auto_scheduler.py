"""自动排产调度器（2026-08-27）——容器内后台线程，随模拟器 tick 周期排产 + FIFO 审批。

三层触发：
  1. cron 周期（本模块主循环）：每 AUTO_SCHEDULE_TICK_INTERVAL tick 跑 run_scheduling + FIFO 审批
  2. 模拟器事件（runner tick 尾 request_rerun）：设备故障/插单/延期告警 → 即时重排兜底
  3. Agent 语义（run_scheduling 工具，已有）：用户提问触发，保持不动
人工审批保持：FIFO 只自动通过「早于最近 top_n」的待审核版本，top_n 内留给人审。

并发：_lock 保证同一时刻仅一个 run_scheduling 在跑（CP-SAT 不可并发）。
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime

from ..config import (
    AUTO_APPROVE_TOP_N, AUTO_SCHEDULE_ENABLED, AUTO_SCHEDULE_TICK_INTERVAL,
    FIFO_AGE_TIMEOUT, SIM_TICK_SECONDS, STATUS_RESERVE_TOP_N,
)

logger = logging.getLogger(__name__)


class AutoScheduler:
    def __init__(self, interval_ticks: int | None = None, approve_top_n: int | None = None,
                 enabled: bool | None = None, reserve_top_n: int | None = None):
        self.interval_ticks = interval_ticks if interval_ticks is not None else AUTO_SCHEDULE_TICK_INTERVAL
        self.approve_top_n = approve_top_n if approve_top_n is not None else AUTO_APPROVE_TOP_N
        self.enabled = enabled if enabled is not None else AUTO_SCHEDULE_ENABLED.lower() != "off"
        # 2026-08-29 各状态留底：自动排产/审批保留各状态最新 N 单不被推进
        self.reserve_top_n = reserve_top_n if reserve_top_n is not None else STATUS_RESERVE_TOP_N
        self._lock = threading.Lock()          # 排产互斥（与 agent/事件并发）
        self._signal = threading.Event()       # 事件即时重排信号
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_sim_time: datetime | None = None  # 上次观测的 sim 时间（变化 = 1 tick）
        self._tick_count = 0                     # 距上次排产累计 tick 数
        self._runs = 0
        self._last_version: int | None = None
        self._last_trigger: str | None = None

    # ---- 生命周期 ----

    def start(self) -> None:
        if not self.enabled or self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, name="auto-scheduler",
                                        daemon=True)
        self._thread.start()
        logger.info("自动排产调度启动: interval=%d tick, top_n=%d",
                    self.interval_ticks, self.approve_top_n)

    def stop(self) -> None:
        self._stop.set()
        self._signal.set()
        if self._thread:
            self._thread.join(timeout=5)

    # ---- 主循环（随模拟器 tick 节流） ----

    def _loop(self) -> None:
        while not self._stop.is_set():
            # 事件即时重排优先；否则按 tick 节流
            if self._signal.is_set():
                self._signal.clear()
                self._run_locked("event")
            else:
                sim_time = self._read_sim_time()
                if sim_time is not None and sim_time != self._last_sim_time:
                    # sim_clock.current_sim_time 每次变化 = 一个 tick；累计满 interval_ticks 排一轮
                    self._tick_count += 1
                    self._last_sim_time = sim_time
                    if self._tick_count >= self.interval_ticks:
                        self._tick_count = 0
                        self._run_locked("tick")
            self._stop.wait(SIM_TICK_SECONDS / 4 or 1)

    def _read_sim_time(self) -> datetime | None:
        try:
            from flex_fab_agent.tools.data import get_connection
            with get_connection() as conn, conn.cursor() as cur:
                cur.execute("SELECT current_sim_time FROM sim_clock WHERE id=1")
                row = cur.fetchone()
                return row[0] if row and row[0] is not None else None
        except Exception as e:
            logger.warning("读 sim_clock 失败: %s", e)
            return None

    # ---- 单轮：排产 + FIFO 审批（带锁） ----

    def run_once(self, trigger: str = "tick") -> bool:
        """供测试/手动调用的单轮入口；enabled=False 时不动作。"""
        if not self.enabled:
            return False
        return self._run_locked(trigger)

    def _run_locked(self, trigger: str) -> bool:
        if not self._lock.acquire(blocking=False):
            logger.info("自动排产取消(%s)：上一轮排产未完成，跳过本轮", trigger)
            return False  # 已有排产在跑，跳过本轮
        try:
            self._auto_schedule(trigger)
            self._fifo_approve()
            self._runs += 1
            self._last_trigger = trigger
            return True
        finally:
            self._lock.release()

    def _auto_schedule(self, trigger: str) -> None:
        """跑一轮排产（求解器自动分配 machine_id），落库版本。

        2026-08-29 各状态留底（规格 §设计）：排产前查待排队订单数——
          ≤ reserve_top_n → 跳过本轮排产（保留全部待排队样本，避免空排产浪费）；
          > reserve_top_n → 取最新 reserve_top_n 单（id 降序）排除出本次求解，
          它们保持待排队不锁定，保证演示任意时刻待排队都有最新样本可查。
        """
        from flex_fab_agent.tools.data import get_connection
        from flex_fab_agent.tools.scheduler_tools import run_scheduling
        from ..observability.operation_log import record_operation
        try:
            sim_time = self._read_sim_time()
            with get_connection() as conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM orders WHERE status='待排队' ORDER BY id DESC")
                pending_ids = [row[0] for row in cur.fetchall()]
            # reserve_top_n=0 表示关闭订单留底守卫（存量 FIFO 测试场景用）
            if self.reserve_top_n > 0 and len(pending_ids) <= self.reserve_top_n:
                logger.info("自动排产跳过(%s)：待排队 %d 单 ≤ 留底 %d，保留样本",
                            trigger, len(pending_ids), self.reserve_top_n)
                return
            exclude = pending_ids[:self.reserve_top_n]  # 最新 top_n（id 降序头部）
            result = run_scheduling(triggered_by=f"auto:{trigger}",
                                    exclude_order_ids=exclude)
            # 操作日志（旁路）：自动排产触发（无条件，§5.3）
            record_operation("auto", "自动排产触发", "ok",
                             summary=f"trigger={trigger}", sim_time=sim_time)
            import re
            m = re.search(r"版本 (\d+)", result)
            if m:
                self._last_version = int(m.group(1))
                # 操作日志（旁路）：自动排产生成版本（正则命中）
                record_operation("auto", "自动排产生成版本", "ok",
                                 summary=f"生成版本 v{self._last_version}",
                                 relate_id=str(self._last_version),
                                 sim_time=sim_time)
        except Exception as e:
            logger.error("自动排产失败(%s): %s", trigger, e)
            record_operation("auto", "自动排产", "fail",
                             summary=f"trigger={trigger} 异常: {e}")

    def _fifo_approve(self) -> None:
        """版本级 FIFO + 超龄兜底（定稿 §3.D）：approver=system。

        ① 保留最近 top_n 待审核版本，更早的自动通过；
        ② 最早待审版本龄期（当前 sim 时间 − 建版 sim 时刻）≥ FIFO_AGE_TIMEOUT 即通过
           ——解决「锁定全部订单后无新单 → 版本数不足 top_n → 永不启动」的停滞；
           无锚点版本（存量/测试直插）视为已超龄最迟下轮通过；建版晚于当前不计龄（非负校验）。
        """
        from flex_fab_agent.tools.data import get_connection
        from flex_fab_agent.tools.scheduler_tools import approve_schedule
        from ..observability.operation_log import record_operation
        try:
            with get_connection() as conn, conn.cursor() as cur:
                # 2026-08-29 已审核留底（规格 §设计）：已审核订单 ≤ top_n → 跳过本轮审批，
                # 版本继续待审核，不促成已审核被上机消耗；超龄兜底仍可最终放行，不会永久卡死。
                # reserve_top_n=0 表示关闭订单留底守卫（存量 FIFO 测试场景用）。
                cur.execute("SELECT COUNT(*) FROM orders WHERE status='已审核'")
                approved_count = cur.fetchone()[0]
                if self.reserve_top_n > 0 and approved_count <= self.reserve_top_n:
                    logger.info("自动审批跳过：已审核订单 %d 单 ≤ 留底 %d，保留样本",
                                approved_count, self.reserve_top_n)
                    return
                cur.execute(
                    "SELECT v.id FROM schedule_versions v "
                    "WHERE v.status='待审核' "
                    "AND EXISTS (SELECT 1 FROM batches b WHERE b.schedule_version_id=v.id) "
                    "ORDER BY v.id")
                ids = [r[0] for r in cur.fetchall()]
                if not ids:
                    return
                # 当前 sim 时间 + 各版本建版 sim 锚点（state_change_log 唯一通道）
                cur.execute("SELECT current_sim_time FROM sim_clock WHERE id=1")
                clock_row = cur.fetchone()
                now = clock_row[0] if clock_row and clock_row[0] is not None else None
                cur.execute(
                    "SELECT entity_id, MAX(sim_time) FROM state_change_log "
                    "WHERE entity_type='version' AND field='created' AND source='solver' "
                    "GROUP BY entity_id")
                anchors = {row[0]: row[1] for row in cur.fetchall()}
            to_approve: set[int] = set()
            # ① topN：早于最近 top_n 的全部通过
            if len(ids) > self.approve_top_n:
                to_approve.update(ids[:-self.approve_top_n])
            # ② 超龄兜底：最早待审版本
            first = ids[0]
            anchor = anchors.get(str(first))
            if anchor is None:
                to_approve.add(first)  # 无锚点视为已超龄，最迟下轮通过
            elif now is not None:
                age_h = (now - anchor).total_seconds() / 3600
                if age_h >= 0 and age_h >= FIFO_AGE_TIMEOUT:  # 非负校验：建版晚于当前不计龄
                    to_approve.add(first)
            for vid in sorted(to_approve):
                approve_schedule(vid, "通过", note="自动审批(FIFO)", approver="system")
                record_operation("auto", "自动审批", "ok",
                                 summary=f"版本 v{vid} FIFO 自动通过",
                                 relate_id=str(vid), sim_time=now)
        except Exception as e:
            logger.error("FIFO 自动审批失败: %s", e)
            record_operation("auto", "自动审批", "fail",
                             summary=f"FIFO 自动审批异常: {e}")

    # ---- 事件即时重排（兜底） ----

    def request_rerun(self) -> None:
        """模拟器事件（设备故障/插单/延期告警）触发即时重排信号。"""
        self._signal.set()

    # ---- 状态 ----

    def status(self) -> dict:
        return {
            "enabled": self.enabled,
            "interval_ticks": self.interval_ticks,
            "approve_top_n": self.approve_top_n,
            "running": bool(self._thread and self._thread.is_alive()),
            "runs": self._runs,
            "last_version": self._last_version,
            "last_trigger": self._last_trigger,
        }


# 进程级单例（2026-08-27，任务 3 步骤 1 前移至本任务）：
# runner / api / 测试经 get_scheduler() 获取同一 AutoScheduler 实例。
_scheduler_instance: AutoScheduler | None = None


def get_scheduler() -> AutoScheduler:
    """进程级单例（供 runner / api / 测试获取）。"""
    global _scheduler_instance
    if _scheduler_instance is None:
        _scheduler_instance = AutoScheduler()
    return _scheduler_instance
