"""订单工具单元测试。直接测真实 CSV 数据（demo/data/orders.csv 15 条）。"""
from demo.tools.order_tools import query_orders, get_order_detail, get_production_status


def test_query_orders_all():
    result = query_orders()
    assert "15 条订单" in result
    assert "ORD001" in result


def test_query_orders_by_status():
    result = query_orders(status="紧急")
    assert "ORD004" in result  # ORD004 是紧急
    assert "ORD002" not in result  # 即将完成，不是紧急


def test_query_orders_by_customer():
    result = query_orders(customer_name="深圳精密")
    assert "深圳精密" in result
    assert "广州航天" not in result


def test_query_orders_customer_level_no_column():
    """customer_level 是 R7 预留参数，orders.csv 无该列 -> 过滤全空返回未找到。"""
    result = query_orders(customer_level="S")
    assert "未找到" in result


def test_query_orders_process_no_column():
    """process 参数类似：orders.csv 无工艺列 -> 全过滤。"""
    result = query_orders(process="3D打印")
    assert "未找到" in result


def test_query_orders_due_before():
    result = query_orders(due_before="2026-07-25")
    assert "ORD002" in result  # 交期 07-24
    assert "ORD008" not in result  # 交期 08-02


def test_query_orders_sort_due():
    result = query_orders(sort_by="due")
    # 交期最早 ORD004(07-23) 应排第一行数据
    # 行结构: 0=共N条 1=空行 2=header 3=分隔 4=第一条
    lines = result.splitlines()
    assert "ORD004" in lines[4]


def test_query_orders_limit():
    result = query_orders(limit=3)
    assert "共 3 条订单" in result


def test_query_orders_no_match():
    result = query_orders(customer_name="不存在的客户XYZ")
    assert "未找到" in result


def test_get_order_detail_existing():
    detail = get_order_detail("ORD001")
    assert "ORD001" in detail
    assert "客户名" in detail


def test_get_order_detail_missing():
    detail = get_order_detail("ORD999")
    assert "未找到订单 ORD999" in detail


def test_get_production_status_existing():
    status = get_production_status("ORD001")
    assert "ORD001" in status
    assert "当前环节" in status


def test_get_production_status_missing():
    status = get_production_status("ORD999")
    assert "未找到订单 ORD999" in status
