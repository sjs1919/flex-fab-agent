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


def test_load_orders_normalizes_csv_columns(monkeypatch):
    """csv 模式：交期/状态列归一为 schema 键，旧状态枚举转新枚举（M6 联调修复）。"""
    monkeypatch.setenv("DEMO_DATA_SOURCE", "csv")
    by_id = {o["id"]: o for o in load_orders()}
    assert by_id["ORD001"]["status"] == "打印中"           # 生产中→打印中
    assert by_id["ORD001"]["due_date"] == "2026-07-25"     # 交期→due_date
    assert by_id["ORD001"]["客户名"] == "深圳精密五金"       # csv 自带客户名保留
    assert by_id["ORD005"]["status"] == "待排队"            # 排期中→待排队
    assert by_id["ORD007"]["status"] == "待排队"            # 待排产→待排队


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
