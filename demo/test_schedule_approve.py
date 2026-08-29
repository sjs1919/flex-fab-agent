"""审批/排产列表端点集成测试（TestClient + 真 MySQL + STS admin token）。"""
import pytest
from fastapi.testclient import TestClient

from demo.api import app
from demo.auth.token_exchange import STS
from demo.tools.data import get_connection


def _admin_token() -> str:
    return STS().issue_user_token("admin-debug", "admin")


@pytest.fixture(scope="module", autouse=True)
def _seeded_pending_version():
    """造 1 个待审核版本供本模块端点测试（自隔离，不依赖跨文件残留的版本）。

    全量套件下本文件顺序最末，前序测试（如 test_e2e_m4a）已清理自建版本；
    直接插版本+批次，避免「应有待审核版本」随套件顺序漂移。
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO schedule_versions (created_at, triggered_by, status) "
                    "VALUES (NOW(), 'test-api', '待审核')")
        vid = cur.lastrowid
        cur.execute(
            "INSERT INTO batches (id, schedule_version_id, process, model_type, "
            "machine_id, start_time, end_time, post_process_end, status, "
            "approval_status, source) VALUES ('TAPV0001', %s, 'SLA', '600', 'M0001', "
            "'2026-09-01 08:00:00', '2026-09-01 10:00:00', '2026-09-01 11:00:00', "
            "'前道', '待审核', '整批')", (vid,))
        conn.commit()
    yield vid
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM approvals WHERE schedule_version_id=%s", (vid,))
        cur.execute("DELETE FROM preprocess_tasks WHERE batch_id='TAPV0001'")
        cur.execute("DELETE FROM batches WHERE schedule_version_id=%s", (vid,))
        cur.execute("DELETE FROM schedule_versions WHERE id=%s", (vid,))
        conn.commit()


def test_versions_list_returns_versions():
    """GET /schedule/versions 返回版本列表（含 id/status/batch_count）。"""
    client = TestClient(app)
    r = client.get("/schedule/versions")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data["versions"], list)
    assert data["versions"], "至少有一个已生成的排产版本"


def test_approve_rejects_without_token():
    """POST /schedule/approve 无 admin token -> 401。"""
    client = TestClient(app)
    r = client.post("/schedule/approve", json={"version_id": 1, "action": "通过"})
    assert r.status_code == 401


def test_approve_flow():
    """审批链路：取最新待审核版本 -> 通过 -> 状态变已审核。"""
    client = TestClient(app)
    tid = _admin_token()
    versions = client.get("/schedule/versions").json()["versions"]
    pending = [v for v in versions if v["status"] == "待审核"]
    assert pending, "应有待审核版本"
    vid = pending[0]["id"]
    try:
        r = client.post("/schedule/approve", json={"version_id": vid, "action": "通过"},
                        headers={"X-Admin-Token": tid})
        assert r.status_code == 200
        assert r.json()["ok"] is True
        # 审计追溯（发现②）：approvals 行 approver 必须是实际 token 持有者，
        # 不得恒为 approve_schedule 的默认值 "reviewer"
        from demo.tools.data import get_connection
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT approver FROM approvals "
                            "WHERE schedule_version_id=%s ORDER BY id DESC LIMIT 1",
                            (vid,))
                row = cur.fetchone()
        assert row is not None, "审批后 approvals 表应有审计行"
        assert row[0] != "reviewer", f"approver 不得为默认值 reviewer，实际 {row[0]!r}"
        assert row[0] == "admin-debug", f"approver 应为 token 持有者，实际 {row[0]!r}"
        # 重新拉列表确认状态
        again = client.get("/schedule/versions").json()["versions"]
        updated = next(v for v in again if v["id"] == vid)
        assert updated["status"] == "已审核"
    finally:
        # DB 回滚（I2 必须修）：断言失败也回滚，避免污染共享库、逐次耗尽待审核版本
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM approvals WHERE schedule_version_id=%s",
                            (vid,))
                cur.execute("UPDATE schedule_versions SET status='待审核' WHERE id=%s",
                            (vid,))
                cur.execute("UPDATE batches SET approval_status='待审核' "
                            "WHERE schedule_version_id=%s", (vid,))
            conn.commit()
