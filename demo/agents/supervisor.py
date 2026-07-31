"""Supervisor Agent -- 多 Agent 系统的调度中心（week4）。

架构：入口 -> 意图路由 -> 鉴权(Token Exchange) -> 分发子 Agent -> 结果聚合 -> LLM 综合。

角色分工：
  Supervisor（本文件）- 调度中心，拆解、分发、汇总
  review_agent        - 风控专家（reviewer 子 Token，权限：订单详情/生产状态/客户）
  production_agent    - 排产专家（scheduler 子 Token，权限：全工具）

工程化改动（vs 原 week4）：
  - 消灭 sys.path.insert，全包内 import
  - 子 Agent 工具调用传子 Token，RBAC 在工具层真生效（缺口#7 修复）
  - LLM 调用统一用 core.llm_client
"""
import json

from ..agents.router import AgentRouter
from ..agents.review_agent import review_order
from ..agents.production_agent import assess_production_feasibility
from ..auth.token_exchange import STS
from ..auth.audit_logger import AuditLogger
from ..core.llm_client import call_llm
from ..prompts.system_prompts import SUPERVISOR_PROMPT
from ..tools.registry import ToolRegistry, build_default_registry


class SupervisorAgent:
    """多 Agent 调度中心。"""

    def __init__(self, registry: ToolRegistry | None = None):
        self.registry = registry or build_default_registry()
        self.router = AgentRouter()
        self.sts = STS()
        self.audit = AuditLogger()
        self.sub_agent_tokens: dict[str, str] = {}

    def _setup_auth(self, user_role: str = "scheduler") -> str:
        """初始化鉴权链路：签发用户 Token -> 交换子 Agent 受限 Token。"""
        user_token = self.sts.issue_user_token("user_001", user_role)
        self.audit.log("issue_token", "system", "STS", {"role": user_role}, "用户 Token 已签发")

        # 为每个子 Agent 交换权限收缩的子 Token（5 分钟有效）
        for agent_name, agent_role in [("review", "reviewer"), ("production", "scheduler")]:
            token, msg = self.sts.exchange(user_token, agent_role, self.audit.trace_id)
            if token:
                self.sub_agent_tokens[agent_name] = token
                self.audit.log("exchange_token", "STS", agent_name,
                               {"parent": user_token[:8], "role": agent_role}, msg)
            else:
                self.audit.log("exchange_token", "STS", agent_name, {}, f"失败：{msg}", "WARN")
        return user_token

    def dispatch_review(self, order_ids: list[str]) -> list[dict]:
        """调度审核 Agent，传 reviewer 子 Token（工具层校验权限）。"""
        if "review" not in self.sub_agent_tokens:
            self.audit.log("dispatch", "supervisor", "review_agent", {}, "无权限", "ERROR")
            return []
        self.audit.log("dispatch", "supervisor", "review_agent", {"orders": order_ids}, "已调度")
        token = self.sts.get_token(self.sub_agent_tokens["review"])
        results = []
        for oid in order_ids:
            result = review_order(oid, self.registry, token, self.audit)
            results.append(result)
            self.audit.log("sub_call", "review_agent", oid, {}, "完成，风险待评")
        return results

    def dispatch_production(self, order_ids: list[str] | None = None) -> dict:
        """调度生产 Agent，传 scheduler 子 Token。"""
        if "production" not in self.sub_agent_tokens:
            self.audit.log("dispatch", "supervisor", "production_agent", {}, "无权限", "ERROR")
            return {}
        self.audit.log("dispatch", "supervisor", "production_agent", {"orders": order_ids}, "已调度")
        token = self.sts.get_token(self.sub_agent_tokens["production"])
        result = assess_production_feasibility(order_ids, self.registry, token, self.audit)
        self.audit.log("sub_call", "production_agent", "feasibility", {}, "完成")
        return result

    def orchestrate(self, query: str) -> dict:
        """编排多 Agent 协作全流程。"""
        print(f"\n{'=' * 60}\n Supervisor 调度\n{'=' * 60}")
        print(f" 请求：{query}")

        # 1. 意图路由
        route_result = self.router.route(query)
        print(f" 路由目标：{route_result['targets']}")

        # 2. 鉴权初始化
        user_token = self._setup_auth()
        print(f" 鉴权链路：已建立（Token: {user_token[:8]}...）")

        # 3. 分发子 Agent（sample 订单；实际应从订单查询获取）
        sample_orders = ["ORD001", "ORD003", "ORD005"]
        review_results, production_result = [], {}
        targets = route_result["targets"]

        if "review" in targets or "full" in targets:
            print(f"\n -> 调度 [审核 Agent] 评估 {len(sample_orders)} 笔订单风险...")
            review_results = self.dispatch_review(sample_orders)

        if "production" in targets or "full" in targets:
            print(f"\n -> 调度 [生产 Agent] 评估产能...")
            production_result = self.dispatch_production(sample_orders)

        if "query" in targets:
            print("\n -> 直接查询（建议走单 Agent 模式）")

        # 4. 结果汇总
        summary = {
            "query": query,
            "route": route_result,
            "review_results": review_results,
            "production_result": production_result,
        }

        # 5. LLM 综合
        synthesis_context = json.dumps({
            "review_results": [
                {"order_id": r["order_id"], "risk_assessment": r.get("risk_assessment", {})}
                for r in review_results
            ],
            "production_feasibility": production_result.get("feasibility_assessment", {}),
        }, ensure_ascii=False, indent=2)
        messages = [
            {"role": "system", "content": SUPERVISOR_PROMPT},
            {"role": "user", "content": f"用户请求：{query}\n\n子 Agent 结果：\n{synthesis_context}\n\n请综合给出排产建议。"},
        ]
        try:
            response = call_llm(messages, max_tokens=800)
            synthesis = response.choices[0].message.content.strip()
        except Exception as e:
            synthesis = f"综合分析失败：{e}"
        summary["synthesis"] = synthesis

        print(f"\n{'=' * 60}\n Supervisor 综合排产建议\n{'=' * 60}")
        print(synthesis)
        print(f"\n{'=' * 60}\n 审计报告\n{'=' * 60}")
        print(self.audit.get_report())
        return summary


def run_supervisor(query: str) -> dict:
    """运行 Supervisor 处理一次查询。"""
    supervisor = SupervisorAgent()
    return supervisor.orchestrate(query)
