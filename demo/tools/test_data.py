"""数据层单元测试（纯函数，直测 CSV 加载/过滤/格式化）。"""
from demo.tools.data import _read_csv, format_table, filter_by, load_orders, load_inventory


def test_read_csv_returns_rows():
    rows = _read_csv("orders.csv")
    assert len(rows) >= 1
    assert "id" in rows[0]


def test_read_csv_missing_file():
    assert _read_csv("nonexistent.csv") == []


def test_load_orders_all():
    orders = load_orders()
    assert len(orders) == 15
    assert all("id" in o for o in orders)


def test_load_orders_tenant_filter():
    # 无 tenant_id 字段时全量返回（向后兼容）
    orders = load_orders(tenant_id="nonexistent_tenant")
    assert orders == []


def test_format_table_markdown():
    rows = [{"a": "1", "b": "2"}, {"a": "3", "b": "4"}]
    table = format_table(rows, ["a", "b"])
    assert "| a | b |" in table
    assert "| 1 | 2 |" in table
    assert "| 3 | 4 |" in table


def test_format_table_empty():
    assert format_table([]) == "（无数据）"


def test_filter_by_and_logic():
    rows = [
        {"id": "ORD001", "状态": "生产中"},
        {"id": "ORD002", "状态": "紧急"},
    ]
    result = filter_by(rows, id="ORD001", 状态="生产中")
    assert len(result) == 1
    assert result[0]["id"] == "ORD001"


def test_filter_by_empty_val_skipped():
    rows = [{"id": "ORD001"}, {"id": "ORD002"}]
    result = filter_by(rows, id="", 状态="")  # 空值跳过，全返回
    assert len(result) == 2
