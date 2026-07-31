"""订单工具 -- 查订单列表 / 详情 / 生产状态。

纯函数版本，供 Agent 直接 import 调用（Demo 稳定性优先，绕开 MCP stdio 进程通信）。
MCP 协议封装见 mcp_servers.py（展示 MCP 架构，可独立 stdio 运行）。

三个工具对应原 week3 order_server，业务域：3D 打印 / CNC 调度。
"""
import json

from .data import load_orders, filter_by, format_table


def _orders_table(orders: list[dict]) -> str:
    """订单列表专用表格，只显示最关键列。"""
    return format_table(orders, ["id", "客户名", "产品", "数量", "交期", "当前环节", "状态"])


def query_orders(status: str = "", customer_name: str = "") -> str:
    """查询订单列表，可按状态和客户名筛选。

    Args:
        status: 订单状态筛选，如"生产中""紧急""待排产""排期中""即将完成"，空=全部
        customer_name: 客户名模糊匹配，如"深圳精密五金"，空=全部
    """
    orders = load_orders()
    if status:
        orders = [o for o in orders if o["状态"] == status]
    if customer_name:
        orders = [o for o in orders if customer_name in o["客户名"]]
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
