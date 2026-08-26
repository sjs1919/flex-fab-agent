"""资源列表端点集成测试（TestClient + 真 MySQL）。"""
from fastapi.testclient import TestClient

from demo.api import app

_CATEGORIES = ["machines", "customers", "orders", "inventory", "batches", "preprocess"]
# solver 输出表（batches/preprocess）在干净库可空（无 seed/生产写入方），
# 其余 4 类 seed 必有数据（machines 7 / customer 5 / orders 40 / inventory 10）
_SEEDED = {"machines", "customers", "orders", "inventory"}


def test_resources_list_returns_items():
    """6 类资源端点均返回 items 列表；seed 4 类非空，solver 输出表允许空。"""
    client = TestClient(app)
    for category in _CATEGORIES:
        r = client.get(f"/resources/{category}")
        assert r.status_code == 200, f"{category}: {r.status_code}"
        items = r.json()["items"]
        assert isinstance(items, list)
        if category in _SEEDED:
            assert items, f"{category}: 应为非空（seed 数据）"


def test_resources_id_descending():
    """items 统一 id 倒序（最新在前）。id 用原始值比较（字符字典序/数值各按其类型）。"""
    client = TestClient(app)
    for category in _CATEGORIES:
        items = client.get(f"/resources/{category}").json()["items"]
        ids = [i["id"] for i in items]
        assert ids == sorted(ids, reverse=True), f"{category}: id 未倒序 {ids[:3]}..."


def test_resources_unknown_404():
    """未知类目 -> 404。"""
    client = TestClient(app)
    r = client.get("/resources/unknown")
    assert r.status_code == 404
