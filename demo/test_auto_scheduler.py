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
    s._fifo_approve()
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, status FROM schedule_versions WHERE id IN (%s,%s,%s,%s,%s) "
                    "ORDER BY id", tuple(ids))
        rows = dict(cur.fetchall())
    for vid in ids[:-2]:
        assert rows[vid] == "已审核", f"最早版本 {vid} 应自动通过"
    for vid in ids[-2:]:
        assert rows[vid] == "待审核", f"最近版本 {vid} 应保留待审"


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
