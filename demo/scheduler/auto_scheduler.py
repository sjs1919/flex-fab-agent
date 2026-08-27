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

from ..config import (
    AUTO_APPROVE_TOP_N, AUTO_SCHEDULE_ENABLED, AUTO_SCHEDULE_TICK_INTERVAL, SIM_TICK_SECONDS,
)

logger = logging.getLogger(__name__)


class AutoScheduler:
    def __init__(self, interval_ticks: int | None = None, approve_top_n: int | None = None,
                 enabled: bool | None = None):
        self.interval_ticks = interval_ticks if interval_ticks is not None else AUTO_SCHEDULE_TICK_INTERVAL
        self.approve_top_n = approve_top_n if approve_top_n is not None else AUTO_APPROVE_TOP_N
        self.enabled = enabled if enabled is not None else AUTO_SCHEDULE_ENABLED.lower() != "off"
        self._lock = threading.Lock()          # 排产互斥（与 agent/事件并发）
        self._signal = threading.Event()       # 事件即时重排信号
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_sim_time: str | None = None  # 上次观测的 sim 时间（变化 = 1 tick）
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

    def _read_sim_time(self) -> str | None:
        try:
            from demo.tools.data import get_connection
            with get_connection() as conn, conn.cursor() as cur:
                cur.execute("SELECT current_sim_time FROM sim_clock WHERE id=1")
                row = cur.fetchone()
                return str(row[0]) if row and row[0] is not None else None
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
        """跑一轮排产（求解器自动分配 machine_id），落库版本。"""
        from demo.tools.scheduler_tools import run_scheduling
        try:
            result = run_scheduling(triggered_by=f"auto:{trigger}")
            import re
            m = re.search(r"版本 (\d+)", result)
            if m:
                self._last_version = int(m.group(1))
        except Exception as e:
            logger.error("自动排产失败(%s): %s", trigger, e)

    def _fifo_approve(self) -> None:
        """版本级 FIFO：保留最近 top_n 待审核版本，更早的有批次版本自动通过（approver=system）。"""
        from demo.tools.data import get_connection
        from demo.tools.scheduler_tools import approve_schedule
        try:
            with get_connection() as conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT v.id FROM schedule_versions v "
                    "WHERE v.status='待审核' "
                    "AND EXISTS (SELECT 1 FROM batches b WHERE b.schedule_version_id=v.id) "
                    "ORDER BY v.id")
                ids = [r[0] for r in cur.fetchall()]
            if len(ids) <= self.approve_top_n:
                return
            for vid in ids[:-self.approve_top_n]:
                approve_schedule(vid, "通过", note="自动审批(FIFO)", approver="system")
        except Exception as e:
            logger.error("FIFO 自动审批失败: %s", e)

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
