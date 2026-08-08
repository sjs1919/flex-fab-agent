"""资源工具单元测试（库存/设备/客户）。"""
from demo.tools.resource_tools import query_inventory, query_machine_load, query_customer


def test_query_inventory_all():
    result = query_inventory()
    assert "种材料" in result
    assert "MAT001" in result or "钛合金" in result


def test_query_inventory_by_material():
    result = query_inventory(material_name="钛合金")
    assert "钛合金" in result


def test_query_inventory_stock_below():
    result = query_inventory(stock_below=30)
    # TC4钛合金粉末库存 25kg 低于 30
    assert "钛合金" in result


def test_query_inventory_no_match():
    result = query_inventory(material_name="不存在材料XYZ")
    assert "未找到" in result


def test_query_machine_load():
    result = query_machine_load()
    assert "设备总数" in result
    assert "M01" in result


def test_query_customer_by_id():
    result = query_customer(customer_id="C001")
    assert "C001" in result


def test_query_customer_by_name():
    result = query_customer(customer_name="深圳")
    assert "深圳" in result


def test_query_customer_min_level():
    # S 级最高：min_level=S 只返回 S 级
    result = query_customer(min_level="S")
    assert "广州航天" in result  # C003 S 级


def test_query_customer_no_match():
    result = query_customer(customer_name="不存在客户XYZ")
    assert "未找到" in result
