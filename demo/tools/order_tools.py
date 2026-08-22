"""订单工具 -- 查订单列表 / 详情 / 生产状态。

纯函数版本，供 Agent 直接 import 调用（Demo 稳定性优先，绕开 MCP stdio 进程通信）。
MCP 协议封装见 mcp_servers.py（展示 MCP 架构，可独立 stdio 运行）。

三个工具对应原 week3 order_server，业务域：3D 打印调度。

M1 T3.1 字段/枚举对齐（v2 重构）：
  列名 → id/customer_id/amount/urgent/priority/due_date/status
  状态枚举 → {待排队,已审核,打印中,完成}（去旧枚举"紧急/生产中/..."）
  客户等级 → S/A/B/C（去 D）
  客户名/客户等级经 customer 表 join；工艺经 part.material join（订单下任一 part 材料）。
"""
import json

from .data import load_customers, load_orders, load_parts, format_table


def _orders_table(orders: list[dict]) -> str:
    """订单列表专用表格，显示最关键列（新表字段 + 派生的客户名）。"""
    return format_table(orders, ["id", "customer_id", "客户名", "amount", "urgent", "priority", "due_date", "status"])


def _enrich(orders: list[dict]) -> list[dict]:
    """为订单补派生字段：客户名/客户等级（customer 表）、工艺（part.material）。"""
    customers = {c["id"]: c for c in load_customers()}
    parts_by_order: dict[str, set] = {}
    for p in load_parts():
        parts_by_order.setdefault(p["order_id"], set()).add(p["material"])
    for o in orders:
        c = customers.get(o.get("customer_id", ""), {})
        o["客户名"] = c.get("name", "")
        o["客户等级"] = c.get("level", "")
        o["工艺"] = ",".join(sorted(parts_by_order.get(o["id"], set())))
        # 数据库原生类型 → 字符串/整数，统一展示与筛选（Decimal/date 不可直接比较）
        if o.get("due_date") is not None:
            o["due_date"] = o["due_date"].strftime("%Y-%m-%d") if hasattr(o["due_date"], "strftime") else str(o["due_date"])
        if o.get("amount") is not None:
            o["amount"] = str(o["amount"])
        if o.get("urgent") is not None:
            o["urgent"] = int(o["urgent"])
    return orders


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
    """查询订单列表，支持多字段 AND 组合筛选和排序。

    筛选字段（全部可选，AND 组合）：
      status          — 订单状态（待排队/已审核/打印中/完成）
      customer_name   — 客户名模糊匹配（经 customer 表）
      customer_level  — 客户等级（S/A/B/C，去 D）
      process         — 工艺（SLA/MJS/SLM，经 part.material）
      due_before      — 交期在指定日期之前 YYYY-MM-DD
      due_after       — 交期在指定日期之后 YYYY-MM-DD
      sort_by         — 排序：priority(权重分降序)/due(交期)/level(客户等级)
      limit           — 返回前 N 条，0=全部
    """
    orders = _enrich(load_orders())
    if status:
        orders = [o for o in orders if o.get("status", "") == status]
    if customer_name:
        orders = [o for o in orders if customer_name in o.get("客户名", "")]
    if customer_level:
        orders = [o for o in orders if o.get("客户等级", "") == customer_level]
    if process:
        orders = [o for o in orders if process in o.get("工艺", "").split(",")]
    if due_before:
        orders = [o for o in orders if o.get("due_date", "") <= due_before]
    if due_after:
        orders = [o for o in orders if o.get("due_date", "") >= due_after]

    # 排序（priority 为真实权重分，降序：高分优先）
    if sort_by == "due":
        orders.sort(key=lambda x: x.get("due_date", "9999-99-99"))
    elif sort_by == "level":
        level_order = {"S": 0, "A": 1, "B": 2, "C": 3}
        orders.sort(key=lambda x: level_order.get(x.get("客户等级", ""), 9))
    elif sort_by == "priority":
        orders.sort(key=lambda x: (-x.get("priority", 0), x.get("due_date", "9999-99-99")))

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
    matched = [o for o in orders if o["id"] == order_id]
    if not matched:
        return f"未找到订单 {order_id}。"
    o = dict(matched[0])
    c = {cc["id"]: cc for cc in load_customers()}.get(o.get("customer_id", ""), {})
    o["客户名"] = c.get("name", "")
    o["客户等级"] = c.get("level", "")
    return json.dumps(o, ensure_ascii=False, indent=2, default=str)


def get_production_status(order_id: str) -> str:
    """获取订单的当前生产状态（简洁文本，快速了解进度）。

    Args:
        order_id: 订单编号，如 ORD001
    """
    orders = load_orders()
    matched = [o for o in orders if o["id"] == order_id]
    if not matched:
        return f"未找到订单 {order_id}。"
    o = matched[0]
    return (f"订单 {o['id']} - {o['status']}\n"
            f"  状态：{o['status']}\n  交期：{o['due_date']}\n  金额：{o['amount']}")
