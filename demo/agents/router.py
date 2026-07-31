"""意图识别路由 -- 入口分类用户请求并分发到对应子 Agent。

基于关键词做意图分类（当前实现；后续可升级为 LLM 路由，见差距表"Agent 编排"项）。
路由目标：
  review     -> 审核 Agent（风险评估）
  production -> 生产 Agent（产能评估）
  full       -> Supervisor 综合（审核 + 生产 + 汇总）
  query      -> 单 Agent 查数据（不需要协作）
"""
from typing import Literal

RouteTarget = Literal["review", "production", "full", "query"]


class AgentRouter:
    """意图识别路由器。"""

    def __init__(self):
        self._routes = {
            "review": ["审核", "风险", "信用", "评级", "异常", "风控"],
            "production": ["设备", "材料", "库存", "负载", "产能", "生产", "机器"],
            "full": ["调度", "排产", "排序", "优先级", "今日", "先做哪些"],
        }

    def classify(self, query: str) -> list[RouteTarget]:
        """基于关键词对用户请求做意图分类。"""
        query_lower = query.lower()
        matched = []
        for route, keywords in self._routes.items():
            for kw in keywords:
                if kw in query_lower:
                    matched.append(route)
                    break
        # 优先匹配 full（综合意图）
        if "full" in matched:
            return ["full"]
        if matched:
            return matched
        # 默认走 query（单 Agent 查数据）
        return ["query"]

    def route(self, query: str, context: dict | None = None) -> dict:
        targets = self.classify(query)
        return {"query": query, "targets": targets, "context": context or {}}
