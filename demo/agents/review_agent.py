"""审核 Agent（子 Agent）-- 风控专家，评估订单风险等级。

职责：客户信用评估 + 订单异常检测 + 风险评级（高/中/低）。
只读数据，不做排产决策。由 Supervisor 调度。

工程化改动（vs 原 week4）：
  - 工具调用走 registry.execute(name, args, token, audit)，不再直接 import
  - 传入 reviewer 子 Token，工具层 RBAC 校验生效（缺口#7 修复）
  - LLM 调用用 core.llm_client.call_llm_simple
"""
import json

from ..core.llm_client import call_llm_simple
from ..prompts.system_prompts import REVIEW_AGENT_PROMPT
from ..tools.registry import ToolRegistry


def _parse_json(text: str) -> dict:
    """从 LLM 输出解析 JSON（兼容 ```json``` 包裹和纯文本）。"""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text}


def build_review_context(order_id: str, registry: ToolRegistry,
                         token=None, audit=None) -> str:
    """构建订单审核上下文（JSON）：订单详情 + 生产状态 + 客户信用。

    三个工具都走 registry，传 token 做权限校验。
    """
    detail = registry.execute("get_order_detail", {"order_id": order_id}, token, audit)
    production = registry.execute("get_production_status", {"order_id": order_id}, token, audit)

    detail_data = json.loads(detail) if detail and detail.startswith("{") else {}
    customer_name = detail_data.get("客户名", "")
    credit_data = {}
    if customer_name:
        credit = registry.execute("query_customer", {"customer_name": customer_name}, token, audit)
        try:
            credit_data = json.loads(credit) if credit.startswith("{") else {"raw": str(credit)}
        except (json.JSONDecodeError, TypeError):
            credit_data = {"raw": str(credit)}

    return json.dumps({
        "order_detail": detail_data,
        "production_status": production,
        "customer_credit": credit_data,
    }, ensure_ascii=False, indent=2)


def review_order(order_id: str, registry: ToolRegistry,
                 token=None, audit=None) -> dict:
    """审核单笔订单：采集上下文 -> 调 LLM -> 返回风险评级。"""
    context = build_review_context(order_id, registry, token, audit)
    try:
        response = call_llm_simple(
            REVIEW_AGENT_PROMPT,
            f"请审核订单 {order_id} 的风险等级。\n\n订单上下文数据：\n{context}",
        )
        risk_data = _parse_json(response.choices[0].message.content)
    except Exception as e:
        risk_data = {"error": str(e), "risk_level": "unknown"}
    return {
        "order_id": order_id,
        "context": context,
        "risk_assessment": risk_data,
        "agent": "review_agent",
        "status": "reviewed",
    }
