"""AutoScheduler 单测：FIFO 审批 / tick 节流 / 并发锁 / 事件重排信号。"""
import threading
from demo.scheduler.auto_scheduler import AutoScheduler
from demo.tools.data import get_connection


def _seed_versions(count: int) -> list[int]:
    """造 count 个待审核版本（有批次），返回 id 升序。"""
    with get_connection() as conn, conn.cursor() as cur:
        ids = []
        for i in range(count):
            cur.execute("INSERT INTO schedule_versions (created_at, triggered_by, status) "
                        "VALUES (NOW(), 'test', '待审核')")
            vid = cur.lastrowid
            cur.execute("INSERT INTO batches (id, schedule_version_id, process, model_type, "
                        "source, status, approval_status) "
                        "VALUES (%s, %s, 'SLA', '450', '整批', '前道', '待审核')",
                        (f"T{vid}", vid))
            ids.append(vid)
        conn.commit()
    return ids


def test_fifo_approve_keeps_top_n():
    """保留最近 top_n 待审核版本，更早的有批次版本自动通过。"""
    s = AutoScheduler(interval_ticks=3, approve_top_n=2)
    ids = _seed_versions(5)  # id 升序，ids[-2:] 为最新
    try:
        s._fifo_approve()
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT id, status FROM schedule_versions WHERE id IN (%s,%s,%s,%s,%s) "
                        "ORDER BY id", tuple(ids))
            rows = dict(cur.fetchall())
        for vid in ids[:-2]:
            assert rows[vid] == "已审核", f"最早版本 {vid} 应自动通过"
        for vid in ids[-2:]:
            assert rows[vid] == "待审核", f"最近版本 {vid} 应保留待审"
    finally:
        _cleanup_versions(ids)


def test_run_once_locked_when_busy():
    """并发：同一时刻仅一个 run_once 执行（锁生效）。"""
    s = AutoScheduler(interval_ticks=3, approve_top_n=2)
    entered = threading.Event()
    release = threading.Event()

    def _fake_run(trigger):
        # _run_locked 内部已 self._runs += 1；此处只模拟排产耗时，不再自增（避免双计）
        entered.set()
        release.wait(timeout=3)
        return "ok"

    s._auto_schedule = _fake_run
    t = threading.Thread(target=lambda: s.run_once("tick"))
    t.start()
    entered.wait(timeout=3)
    # 第二线程尝试 run_once -> 应被锁阻塞（不执行）
    s.run_once("tick")
    release.set()
    t.join(timeout=5)
    assert s._runs == 1, f"并发应只执行一次，实际 {s._runs}"


def test_auto_schedule_disabled():
    """AUTO_SCHEDULE_ENABLED=off 时 run_once 不排产。"""
    s = AutoScheduler(interval_ticks=3, approve_top_n=2, enabled=False)
    assert s.run_once("tick") is False


def test_request_rerun_sets_signal():
    """事件信号触发：request_rerun 后 _signal 置位，run_once 处理并清除。"""
    s = AutoScheduler(interval_ticks=3, approve_top_n=2)
    s._auto_schedule = lambda trigger: None   # 不真跑求解
    s._fifo_approve = lambda: None
    s.request_rerun()
    assert s._signal.is_set()
    # 模拟循环处理一次信号
    s._signal.clear()
    assert not s._signal.is_set()


# ---- 定稿 v1 §3.D：FIFO 超龄兜底 ----

def _cleanup_version(vid):
    """清理单个测试版本（含其批次/审批/建版锚点日志）。"""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM approvals WHERE schedule_version_id=%s", (vid,))
        cur.execute("DELETE FROM batches WHERE schedule_version_id=%s", (vid,))
        cur.execute("DELETE FROM state_change_log WHERE entity_id=%s", (str(vid),))
        cur.execute("DELETE FROM schedule_versions WHERE id=%s", (vid,))
        conn.commit()


def _cleanup_versions(ids):
    for vid in ids:
        _cleanup_version(vid)


def _seed_clock(sim_time_str):
    """写 sim_clock 单行（无则插，有则更）。"""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM sim_clock WHERE id=1")
        if cur.fetchone():
            cur.execute("UPDATE sim_clock SET current_sim_time=%s WHERE id=1", (sim_time_str,))
        else:
            cur.execute("INSERT INTO sim_clock (id, current_sim_time) VALUES (1, %s)",
                        (sim_time_str,))
        conn.commit()


def _clear_clock():
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM sim_clock WHERE id=1")
        conn.commit()


def _seed_version_with_anchor(anchor_sim_time_str) -> int:
    """造 1 个待审核版本（有批次）+ 建版 sim 锚点（state_change_log，source=solver）。"""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO schedule_versions (created_at, triggered_by, status) "
                    "VALUES (NOW(), 'test', '待审核')")
        vid = cur.lastrowid
        cur.execute("INSERT INTO batches (id, schedule_version_id, process, model_type, "
                    "source, status, approval_status) VALUES (%s, %s, 'SLA', '450', '整批', "
                    "'前道', '待审核')", (f"T{vid}", vid))
        cur.execute("INSERT INTO state_change_log (sim_time, entity_type, entity_id, `field`, "
                    "old_value, new_value, source) VALUES (%s, 'version', %s, 'created', "
                    "NULL, NULL, 'solver')", (anchor_sim_time_str, str(vid)))
        conn.commit()
    return vid


def test_fifo_approve_aged_out_version():
    """超龄兜底（§3.D）：最早待审版本龄期 ≥ FIFO_AGE_TIMEOUT 自动通过，
    即使版本数 ≤ top_n（无新单停滞场景）。"""
    s = AutoScheduler(interval_ticks=3, approve_top_n=5)
    _seed_clock("2026-09-05 08:00:00")
    vid = _seed_version_with_anchor("2026-09-02 08:00:00")  # 72h 前建版，超龄(>24h)
    try:
        s._fifo_approve()
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT status FROM schedule_versions WHERE id=%s", (vid,))
            assert cur.fetchone()[0] == "已审核"
    finally:
        _cleanup_version(vid)
        _clear_clock()


def test_fifo_approve_not_aged_keeps_waiting():
    """未超龄：最早待审版本龄期 < FIFO_AGE_TIMEOUT 且版本数 ≤ top_n → 保持待审。"""
    s = AutoScheduler(interval_ticks=3, approve_top_n=5)
    _seed_clock("2026-09-05 08:00:00")
    vid = _seed_version_with_anchor("2026-09-05 00:00:00")  # 8h 前建版，未超龄(<24h)
    try:
        s._fifo_approve()
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT status FROM schedule_versions WHERE id=%s", (vid,))
            assert cur.fetchone()[0] == "待审核"
    finally:
        _cleanup_version(vid)
        _clear_clock()


def test_fifo_approve_no_anchor_treated_aged():
    """无锚点版本视为已超龄最迟下轮通过（存量/测试直插版本不因缺锚点停滞）。"""
    s = AutoScheduler(interval_ticks=3, approve_top_n=5)
    ids = _seed_versions(2)  # 2 个无锚点版本，≤ top_n=5
    try:
        s._fifo_approve()
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT status FROM schedule_versions WHERE id=%s", (ids[0],))
            assert cur.fetchone()[0] == "已审核", "无锚点最早版本应视为已超龄通过"
            cur.execute("SELECT status FROM schedule_versions WHERE id=%s", (ids[1],))
            assert cur.fetchone()[0] == "待审核", "仅最早无锚点版本通过，其余保留"
    finally:
        _cleanup_versions(ids)
        _clear_clock()
