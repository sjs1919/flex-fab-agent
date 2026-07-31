"""资源工具 -- 查材料库存 / 设备负载 / 客户信息。

纯函数版本，对应原 week3 resource_server。与 order_tools 共享同一数据层，
但暴露不同的工具视图（类比微服务的两个独立服务，各有数据库视图）。
"""
import json

from .data import load_inventory, load_machines, load_customers, filter_by, format_table


def query_inventory(material_name: str = "") -> str:
    """查询材料库存，可按材料名模糊搜索。

    Args:
        material_name: 材料名关键词，如"钛合金""铝合金"，空=全部
    """
    items = load_inventory()
    if material_name:
        items = [i for i in items if material_name in i["材料名"] or material_name in i["名称"]]
    if not items:
        return f"未找到匹配 {material_name} 的材料。"
    return (f"共 {len(items)} 种材料：\n\n"
            + format_table(items, ["名称", "材料名", "库存量", "单位", "安全库存", "采购周期天", "单价"]))


def query_machine_load() -> str:
    """查询所有设备负载状态--哪些在运行、哪些空闲、预计何时释放。

    无参数。Agent 排产决策的关键依据：哪些设备有空，哪些在忙。
    """
    machines = load_machines()
    running = [m for m in machines if m["状态"] == "运行中"]
    idle = [m for m in machines if m["状态"] == "空闲"]
    return "\n".join([
        f"设备总数：{len(machines)} 台（运行中 {len(running)} / 空闲 {len(idle)}）\n",
        format_table(machines, ["machine_id", "型号", "类型", "当前订单", "预计空闲时间", "状态"]),
    ])


def query_customer(customer_id: str = "", customer_name: str = "") -> str:
    """查询客户信息--等级、信用分、历史延期率、行业。

    Args:
        customer_id: 客户编号，如 C001
        customer_name: 客户名模糊匹配，如"深圳"
    """
    customers = load_customers()
    if customer_id:
        customers = filter_by(customers, id=customer_id)
    if customer_name:
        customers = [c for c in customers if customer_name in c["名称"]]
    if not customers:
        return "未找到匹配的客户。"
    if len(customers) == 1:
        return json.dumps(customers[0], ensure_ascii=False, indent=2)
    return (f"共 {len(customers)} 个客户：\n\n"
            + format_table(customers, ["id", "名称", "等级", "信用分", "历史延期率", "行业"]))
