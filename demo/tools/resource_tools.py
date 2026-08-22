"""资源工具 -- 查材料库存 / 设备负载 / 客户信息。

纯函数版本，对应原 week3 resource_server。与 order_tools 共享同一数据层，
但暴露不同的工具视图（类比微服务的两个独立服务，各有数据库视图）。

R7 缺陷修复（2026-08-07）：query_inventory 和 query_customer 增强为多字段筛选 + 排序。
"""
import json

from .data import load_inventory, load_machines, load_customers, filter_by, format_table


def query_inventory(material_name: str = "", category: str = "",
                    stock_below: float = 0, sort_by: str = "") -> str:
    """查询材料库存，可按材料名、类别、库存量筛选和排序（R7 增强）。

    Args:
        material_name: 材料名关键词，如"钛合金""铝合金"，空=全部
        category: 材料类别（金属/塑料/复合材料），空=全部（R7新增）
        stock_below: 库存低于此数值的材料，空=不限（R7新增）
        sort_by: 排序方式 stock_asc(库存从少到多)，空=不排序（R7新增）
    """
    items = load_inventory()
    if material_name:
        items = [i for i in items if material_name in i.get("材料名", "") or material_name in i.get("名称", "")]
    if category:
        items = [i for i in items if i.get("类别", "") == category]
    if stock_below > 0:
        items = [i for i in items if float(i.get("库存量", 0)) < stock_below]
    if sort_by == "stock_asc":
        items.sort(key=lambda x: float(x.get("库存量", 99999)))
    if not items:
        return f"未找到匹配 {material_name} 的材料。"
    return (f"共 {len(items)} 种材料：\n\n"
            + format_table(items, ["名称", "材料名", "库存量", "单位", "安全库存", "采购周期天", "单价"]))


def query_machine_load() -> str:
    """查询所有设备负载状态--哪些在打印、哪些空闲、各机舱规格。

    无参数。Agent 排产决策的关键依据：哪些设备有空，哪些在忙。
    状态枚举（M1 T3.2）：{空闲,打印中,故障,维修中,静置中}。
    """
    machines = load_machines()
    busy = [m for m in machines if m.get("status", "") == "打印中"]
    idle = [m for m in machines if m.get("status", "") == "空闲"]
    return "\n".join([
        f"设备总数：{len(machines)} 台（打印中 {len(busy)} / 空闲 {len(idle)}）\n",
        format_table(machines, ["id", "name", "process", "model_type", "cabin_size", "max_weight", "status"]),
    ])


def query_customer(customer_id: str = "", customer_name: str = "",
                   min_level: str = "", sort_by: str = "") -> str:
    """查询客户信息--等级、信用分、折扣率、行业、违约金日费率（R7 增强，M1 T3.2 对齐新表）。

    Args:
        customer_id: 客户编号，如 C001
        customer_name: 客户名模糊匹配，如"深圳"
        min_level: 最低等级（S/A/B/C），空=全部（去 D）
        sort_by: 排序 level(等级)/credit(信用分)，空=不排序
    """
    customers = load_customers()
    if customer_id:
        customers = filter_by(customers, id=customer_id)
    if customer_name:
        customers = [c for c in customers if customer_name in c.get("name", "")]
    if min_level:
        level_order = {"S": 0, "A": 1, "B": 2, "C": 3}
        min_val = level_order.get(min_level, 9)
        customers = [c for c in customers if level_order.get(c.get("level", ""), 9) <= min_val]
    if sort_by == "level":
        level_order = {"S": 0, "A": 1, "B": 2, "C": 3}
        customers.sort(key=lambda x: level_order.get(x.get("level", ""), 9))
    elif sort_by == "credit":
        customers.sort(key=lambda x: int(x.get("credit_score", 0)), reverse=True)
    if not customers:
        return "未找到匹配的客户。"
    if len(customers) == 1:
        return json.dumps(customers[0], ensure_ascii=False, indent=2, default=str)
    return (f"共 {len(customers)} 个客户：\n\n"
            + format_table(customers, ["id", "name", "level", "credit_score", "discount_rate", "industry", "penalty_rate"]))
