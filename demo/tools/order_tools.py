"""订单工具 -- 查订单列表 / 详情 / 生产状态。

纯函数版本，供 Agent 直接 import 调用（Demo 稳定性优先，绕开 MCP stdio 进程通信）。
MCP 协议封装见 mcp_servers.py（展示 MCP 架构，可独立 stdio 运行）。

三个工具对应原 week3 order_server，业务域：3D 打印 / CNC 调度。

R7 缺陷修复（2026-08-07）：query_orders 增强为多字段 AND 组合筛选 + 排序 + limit。
"""
import json

from .data import load_orders, filter_by, format_table


def _orders_table(orders: list[dict]) -> str:
    """订单列表专用表格，只显示最关键列。"""
    return format_table(orders, ["id", "客户名", "产品", "数量", "交期", "当前环节", "状态"])


def query_orders(
    status: str = "",
    customer_name: str = "",
    customer_level: str = "",
    process: str = "",
    due_before: str = "",
    due_after: str = "",
    sort_by: str = "",
    limit: int = 0,
) -> str:
    """查询订单列表，支持多字段 AND 组合筛选和排序（R7 增强）。

    筛选字段（全部可选，AND 组合）：
      status          — 订单状态（紧急/生产中/待排产/排期中/即将完成）
      customer_name   — 客户名模糊匹配
      customer_level  — 客户等级（S/A/B/C/D）（R7新增）
      process         — 工艺类型（3D打印/CNC/注塑/表面处理）（R7新增）
      due_before      — 交期在指定日期之前 YYYY-MM-DD（R7新增）
      due_after       — 交期在指定日期之后 YYYY-MM-DD（R7新增）
      sort_by         — 排序：priority(综合优先级)/due(交期)/level(客户等级)（R7新增）
      limit           — 返回前 N 条，0=全部（R7新增）
    """
    orders = load_orders()
    if status:
        orders = [o for o in orders if o["状态"] == status]
    if customer_name:
        orders = [o for o in orders if customer_name in o["客户名"]]
    if customer_level:
        orders = [o for o in orders if o.get("客户等级", "") == customer_level]
    if process:
        orders = [o for o in orders if o.get("工艺", "") == process]
    if due_before:
        orders = [o for o in orders if o.get("交期", "") <= due_before]
    if due_after:
        orders = [o for o in orders if o.get("交期", "") >= due_after]

    # 排序
    if sort_by == "due":
        orders.sort(key=lambda x: x.get("交期", "9999-99-99"))
    elif sort_by == "level":
        level_order = {"S": 0, "A": 1, "B": 2, "C": 3, "D": 4}
        orders.sort(key=lambda x: level_order.get(x.get("客户等级", ""), 5))
    elif sort_by == "priority":
        level_order = {"S": 0, "A": 1, "B": 2, "C": 3, "D": 4}
        status_order = {"紧急": 0, "生产中": 1, "待排产": 2, "排期中": 3, "即将完成": 4}
        orders.sort(key=lambda x: (
            status_order.get(x.get("状态", ""), 9),
            x.get("交期", "9999-99-99"),
            level_order.get(x.get("客户等级", ""), 5),
        ))

    # limit
    if limit > 0:
        orders = orders[:limit]

    if not orders:
        return "未找到匹配的订单。"

    return f"共 {len(orders)} 条订单：\n\n{_orders_table(orders)}"


def get_order_detail(order_id: str) -> str:
    """获取单个订单的完整信息（JSON 格式，适合 LLM 深度分析）。

    Args:
        order_id: 订单编号，如 ORD001
    """
    orders = load_orders()
    matched = filter_by(orders, id=order_id)
    if not matched:
        return f"未找到订单 {order_id}。"
    return json.dumps(matched[0], ensure_ascii=False, indent=2)


def get_production_status(order_id: str) -> str:
    """获取订单的当前生产环节和状态（简洁文本，快速了解进度）。

    Args:
        order_id: 订单编号，如 ORD001
    """
    orders = load_orders()
    matched = filter_by(orders, id=order_id)
    if not matched:
        return f"未找到订单 {order_id}。"
    o = matched[0]
    return (f"订单 {o['id']} - {o['产品']}\n"
            f"  当前环节：{o['当前环节']}\n  状态：{o['状态']}\n  交期：{o['交期']}")
