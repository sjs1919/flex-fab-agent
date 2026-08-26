"""审批/排产列表端点集成测试（TestClient + 真 MySQL + STS admin token）。"""
from fastapi.testclient import TestClient

from demo.api import app
from demo.auth.token_exchange import STS


def _admin_token() -> str:
    return STS().issue_user_token("admin-debug", "admin")


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
    # DB 回滚（fix-2）：审批副作用恢复为待审核，保证测试可重复
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM approvals WHERE schedule_version_id=%s",
                        (vid,))
            cur.execute("UPDATE schedule_versions SET status='待审核' WHERE id=%s",
                        (vid,))
            cur.execute("UPDATE batches SET approval_status='待审核' "
                        "WHERE schedule_version_id=%s", (vid,))
        conn.commit()
