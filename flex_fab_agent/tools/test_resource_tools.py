"""资源工具单元测试（M1 T3.2 同步：mysql 种子数据口径）。

设备 7 台 M0001-M0007（全空闲）；客户 C001=深圳精密五金(A)、C003=广州航天精工(S)。
"""
import os

import pytest

import flex_fab_agent.simulator.seed as seed_mod
from flex_fab_agent.tools.resource_tools import query_customer, query_inventory, query_machine_load


@pytest.fixture(scope="module", autouse=True)
def seeded_mysql():
    seed_mod.reset()
    os.environ["DEMO_DATA_SOURCE"] = "mysql"
    yield
    os.environ["DEMO_DATA_SOURCE"] = "csv"


def test_query_inventory_all():
    result = query_inventory()
    assert "种材料" in result
    assert "铝合金" in result  # MAT001 AlSi10Mg铝合金粉末


def test_query_inventory_by_material():
    result = query_inventory(material_name="钛合金")
    assert "钛合金" in result


def test_query_inventory_stock_below():
    result = query_inventory(stock_below=30)
    assert "钛合金" in result  # TC4钛合金粉末 25kg < 30


def test_query_inventory_no_match():
    result = query_inventory(material_name="不存在材料XYZ")
    assert "未找到" in result


def test_query_machine_load():
    """设备状态枚举新口径：打印中/空闲；表头含 process/model_type/cabin_size/max_weight。"""
    result = query_machine_load()
    assert "设备总数" in result
    assert "M0001" in result
    assert "process" in result and "cabin_size" in result and "max_weight" in result


def test_query_customer_by_id():
    result = query_customer(customer_id="C001")
    assert "C001" in result
    assert "深圳精密五金" in result  # name 列（新表）


def test_query_customer_by_name():
    result = query_customer(customer_name="深圳")
    assert "深圳" in result


def test_query_customer_min_level_no_d():
    """min_level 用新枚举（去 D）：S 级只返回广州航天精工。"""
    result = query_customer(min_level="S")
    assert "广州航天" in result


def test_query_customer_no_match():
    result = query_customer(customer_name="不存在客户XYZ")
    assert "未找到" in result
