"""生产 Agent（子 Agent）-- 排产专家，评估生产能力可行性。

职责：材料可行性 + 设备可行性 + 交期可行性。由 Supervisor 调度。

工程化改动：同 review_agent，工具走 registry + 传 scheduler 子 Token。
"""
import json

from ..core.llm_client import call_llm_simple
from ..prompts.system_prompts import PRODUCTION_AGENT_PROMPT
from ..tools.registry import ToolRegistry


def _parse_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text}


def assess_production_feasibility(order_ids: list[str] | None = None,
                                 registry: ToolRegistry = None,
                                 token=None, audit=None) -> dict:
    """综合评估生产能力：查库存 + 查设备 -> 调 LLM 给可行性判断。"""
    material = registry.execute("query_inventory", {}, token, audit)
    machine = registry.execute("query_machine_load", {}, token, audit)
    context = json.dumps({
        "material": material,
        "machine": machine,
        "orders_to_check": order_ids or [],
    }, ensure_ascii=False, indent=2)
    try:
        response = call_llm_simple(
            PRODUCTION_AGENT_PROMPT,
            f"请评估以下订单的生产可行性。\n\n当前资源数据：\n{context}",
        )
        feasibility_data = _parse_json(response.choices[0].message.content)
    except Exception as e:
        feasibility_data = {"error": str(e)}
    return {
        "agent": "production_agent",
        "type": "feasibility_report",
        "material": material,
        "machine": machine,
        "orders_to_check": order_ids or [],
        "feasibility_assessment": feasibility_data,
    }
