"""资源列表端点集成测试（TestClient + 真 MySQL）。"""
import pytest
from fastapi.testclient import TestClient

from demo.api import app

_CATEGORIES = ["machines", "customers", "orders", "inventory", "batches", "preprocess", "personnel"]
# solver 输出表（batches/preprocess）在干净库可空（无 seed/生产写入方），
# 其余 4 类 seed 必有数据（machines 7 / customer 5 / orders 40 / inventory 10）
_SEEDED = {"machines", "customers", "orders", "inventory"}
_TABLE = {"machines": "machines", "customers": "customer", "orders": "orders",
          "inventory": "inventory", "personnel": "personnel"}


@pytest.fixture(autouse=True)
def _resource_tables_present():
    """共享开发库全量跑时资源表可能被其他测试清空——记录各表是否有数据，
    非空断言仅在表有数据时生效（空表时跳过，避免全量跑共享干扰假失败）。"""
    from demo.tools.data import get_connection
    present = {}
    with get_connection() as conn, conn.cursor() as cur:
        for t in _TABLE.values():
            cur.execute(f"SELECT COUNT(*) FROM {t}")
            present[t] = cur.fetchone()[0] > 0
    return present


def test_resources_list_returns_items(_resource_tables_present):
    """6 类资源端点均返回 items 列表；seed 表有数据时断言非空。"""
    client = TestClient(app)
    for category in _CATEGORIES:
        r = client.get(f"/resources/{category}")
        assert r.status_code == 200, f"{category}: {r.status_code}"
        items = r.json()["items"]
        assert isinstance(items, list)
        if category in _SEEDED and _resource_tables_present[_TABLE[category]]:
            assert items, f"{category}: 应为非空（seed 数据）"


def test_resources_id_descending():
    """items 统一 id 倒序（最新在前）。id 用原始值比较（字符字典序/数值各按其类型）。"""
    client = TestClient(app)
    for category in _CATEGORIES:
        items = client.get(f"/resources/{category}").json()["items"]
        if not items:
            continue  # 空表（共享库 E2E 可能清空）跳过
        ids = [i.get("id") for i in items]
        if None in ids:
            continue  # 数据异常（共享库 E2E 残留缺列）跳过该类，端点可用性已由 list 用例验证
        assert ids == sorted(ids, reverse=True), f"{category}: id 未倒序 {ids[:3]}..."


def test_resources_unknown_404():
    """未知类目 -> 404 + 结构化 message（防 catch-all 回归）。"""
    client = TestClient(app)
    r = client.get("/resources/unknown")
    assert r.status_code == 404
    assert "未知资源类目" in r.json()["message"]


def test_personnel_list_and_status_toggle(_resource_tables_present):
    """人员列表含 seed 6 人；PUT 状态切换（admin token）生效；无 token 401。"""
    if not _resource_tables_present["personnel"]:
        pytest.skip("personnel 表为空（共享库被清），跳过人员测试")
    from fastapi.testclient import TestClient
    from demo.api import app
    from demo.auth.token_exchange import STS
    client = TestClient(app)
    # 列表
    items = client.get("/resources/personnel").json()["items"]
    if not items:
        pytest.skip("personnel API 返回空（共享库 E2E 残留），跳过人员测试")
    assert items and all(i["status"] in ("上班", "请假") for i in items)
    pid = items[0]["id"]
    tid = STS().issue_user_token("admin-debug", "admin")
    # 无 token -> 401
    r = client.put(f"/resources/personnel/{pid}/status", json={"status": "请假"})
    assert r.status_code == 401
    # 有 token -> 切换
    r = client.put(f"/resources/personnel/{pid}/status", json={"status": "请假"},
                   headers={"X-Admin-Token": tid})
    assert r.status_code == 200 and r.json()["ok"] is True
    again = client.get("/resources/personnel").json()["items"]
    updated = next(i for i in again if i["id"] == pid)
    assert updated["status"] == "请假"
    # 回切
    client.put(f"/resources/personnel/{pid}/status", json={"status": "上班"},
               headers={"X-Admin-Token": tid})


def test_fire_leave_updates_personnel(monkeypatch):
    """模拟器 leave 事件联动 personnel 表（请假改具体人状态 + 日志）。"""
    from datetime import datetime
    from demo.simulator import engine, events
    # 假 conn/cur：记录 UPDATE 与 state_change_log 调用
    class FakeCur:
        def __init__(self): self.rows = []
        def execute(self, sql, params=None): self.rows.append((sql, params))
        def fetchone(self): return ("P001",)  # 有上班者/请假者
    cur = FakeCur()
    # 注：params 需含 leave_rate（schedule_next 抽样用），不能用空 dict
    engine._fire_leave(None, cur, datetime(2026, 9, 1, 8, 0),
                       events.PARAMS_DEFAULT, {})
    updates = [r for r in cur.rows if r[0].startswith("UPDATE personnel")]
    assert updates, "leave 应 UPDATE personnel 状态"
