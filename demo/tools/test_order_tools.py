"""订单工具单元测试（M1 T3.1 同步：mysql 种子数据口径）。

直接测真实 MySQL 种子数据（seed --reset：5 客户 / 40 订单 / 348 part）。
C001=深圳精密五金(A)、C003=广州航天精工(S)；订单每 5 单循环 1 次 C001。
"""
import os

import pytest

import demo.simulator.seed as seed_mod
from demo.tools.order_tools import get_order_detail, get_production_status, query_orders


@pytest.fixture(scope="module", autouse=True)
def seeded_mysql():
    """模块级：重置种子数据到 MySQL + 数据源指向 mysql。"""
    seed_mod.reset()
    os.environ["DEMO_DATA_SOURCE"] = "mysql"
    yield
    os.environ["DEMO_DATA_SOURCE"] = "csv"


def test_query_orders_all():
    result = query_orders()
    assert "40 条订单" in result
    assert "ORD001" in result


def test_query_orders_by_status_new_enum():
    """状态筛选用新枚举：待排队 命中，旧枚举"紧急" 不再命中。"""
    result = query_orders(status="待排队")
    assert "40 条订单" in result
    result = query_orders(status="紧急")
    assert "未找到" in result  # 新枚举无"紧急"


def test_query_orders_by_customer_name():
    """customer_name 经 customer 表 join 后仍可模糊筛选。"""
    result = query_orders(customer_name="深圳精密")
    assert "深圳精密" in result
    assert "广州航天" not in result


def test_query_orders_customer_level():
    """customer_level 过滤（等级去 D）：A 级客户是深圳精密五金（C001）。"""
    result = query_orders(customer_level="A")
    assert "共 8 条订单" in result  # 40 单 / 5 客户循环，C001 占 8 单
    assert "ORD001" in result


def test_query_orders_process_by_material():
    """process 经 part.material join：SLA/MJS/SLM 任一命中。"""
    result = query_orders(process="SLA")
    assert "条订单" in result and "未找到" not in result


def test_query_orders_sort_level_no_d():
    """sort_by=level：S 级客户订单排最前。"""
    result = query_orders(sort_by="level", limit=3)
    lines = result.splitlines()
    assert "广州航天" in lines[4]  # C003=S 级


def test_query_orders_due_before():
    """due_before 用 due_date 列。"""
    result = query_orders(due_before="2026-09-10")
    assert "条订单" in result


def test_query_orders_sort_due():
    result = query_orders(sort_by="due")
    lines = result.splitlines()
    assert "ORD" in lines[4]  # 最早交期排第一行


def test_query_orders_limit():
    result = query_orders(limit=3)
    assert "共 3 条订单" in result


def test_query_orders_no_match():
    result = query_orders(customer_name="不存在的客户XYZ")
    assert "未找到" in result


def test_get_order_detail_existing():
    detail = get_order_detail("ORD001")
    assert "ORD001" in detail
    assert "customer_id" in detail
    assert "amount" in detail


def test_get_order_detail_missing():
    detail = get_order_detail("ORD999")
    assert "未找到订单 ORD999" in detail


def test_get_production_status_existing():
    status = get_production_status("ORD001")
    assert "ORD001" in status
    assert "状态" in status


def test_get_production_status_missing():
    status = get_production_status("ORD999")
    assert "未找到订单 ORD999" in status
