"""资源列表端点集成测试（TestClient + 真 MySQL）。"""
from fastapi.testclient import TestClient

from demo.api import app

_CATEGORIES = ["machines", "customers", "orders", "inventory", "batches", "preprocess"]


def test_resources_list_returns_items():
    """6 类资源均返回非空 items 列表。"""
    client = TestClient(app)
    for category in _CATEGORIES:
        r = client.get(f"/resources/{category}")
        assert r.status_code == 200, f"{category}: {r.status_code}"
        items = r.json()["items"]
        assert isinstance(items, list)
        assert items, f"{category}: 应为非空（seed 数据）"


def test_resources_id_descending():
    """items 统一 id 倒序（最新在前）。"""
    client = TestClient(app)
    for category in _CATEGORIES:
        items = client.get(f"/resources/{category}").json()["items"]
        ids = [str(i["id"]) for i in items]
        assert ids == sorted(ids, reverse=True), f"{category}: id 未倒序 {ids[:3]}..."


def test_resources_unknown_404():
    """未知类目 -> 404。"""
    client = TestClient(app)
    r = client.get("/resources/unknown")
    assert r.status_code == 404
