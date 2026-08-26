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
    # 重新拉列表确认状态
    again = client.get("/schedule/versions").json()["versions"]
    updated = next(v for v in again if v["id"] == vid)
    assert updated["status"] == "已审核"
