"""工具注册中心 -- 集中管理工具的注册(Schema) + 发现 + 执行。

为什么用注册中心：
  week2 是硬编码 TOOLS 列表 + execute_tool() 的 if/elif 分支（O(n) 线性查找，脆弱）。
  注册中心改为 O(1) 字典查找 + 参数白名单过滤（防 LLM 传多余字段）。
  Agent 通过 registry.get_tool_defs() 拿工具 schema 给 LLM，
  通过 registry.execute(name, args) 执行，两者解耦。

Step 4 已在 build_default_registry() 追加注册 search_knowledge_base（RAG 工具，懒加载）。
"""
from dataclasses import dataclass, field
from typing import Any, Callable

from .order_tools import query_orders, get_order_detail, get_production_status
from .resource_tools import query_inventory, query_machine_load, query_customer


@dataclass
class ToolSchema:
    """工具的标准化定义（OpenAI Function Calling + MCP 协议共同要求）。

    name/description/parameters 是 LLM 选择工具的依据：
      description 最重要--LLM 据此决定何时调用该工具，写清正负示例比单纯描述更有效。
    server 是所属 MCP server 名，用于日志分组（order_server / resource_server）。
    """
    name: str
    description: str
    parameters: dict  # JSON Schema: {type: object, properties: {...}, required: [...]}
    category: str = "general"
    server: str = ""


class ToolRegistry:
    """工具注册中心 -- 管理所有工具的生命周期。

    核心方法：
      register()       注册工具（Schema + Handler 一起）
      get_tool_defs()  返回 OpenAI Function Calling 格式列表，直接传给 LLM
      execute()        按名执行工具，返回结果字符串
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolSchema] = {}
        self._handlers: dict[str, Callable] = {}

    def register(self, name: str, description: str, parameters: dict,
                 handler: Callable[..., Any], category: str = "general",
                 server: str = "") -> None:
        """注册一个工具。一次调用完成 Schema 定义 + Handler 绑定。"""
        if name in self._tools:
            raise ValueError(f"工具 '{name}' 已注册，不能重复注册")
        self._tools[name] = ToolSchema(name, description, parameters, category, server)
        self._handlers[name] = handler

    def get_tool_defs(self) -> list[dict]:
        """返回 OpenAI Function Calling 格式的工具列表，可直接传给 API 的 tools 参数。"""
        return [
            {
                "type": "function",
                "function": {
                    "name": s.name,
                    "description": s.description,
                    "parameters": s.parameters,
                },
            }
            for s in self._tools.values()
        ]

    def get_schema(self, name: str) -> ToolSchema | None:
        return self._tools.get(name)

    def list_all(self) -> list[str]:
        return list(self._tools.keys())

    def execute(self, name: str, arguments: dict,
                token=None, audit=None) -> str:
        """执行指定工具，返回结果字符串。

        参数白名单过滤：只传 Schema 中定义的参数，防 LLM 传多余字段。
        鉴权（洋葱第 3 层）：传入 token 则强制 RBAC 校验，无权则拒绝并审计。
          token/audit 为 None 时放行（兼容单 Agent 无鉴权模式）。
        """
        if name not in self._handlers:
            return f"❌ 未知工具: '{name}'。可用: {', '.join(self.list_all())}"

        # 工具层权限校验（缺口#7 修复：让鉴权真生效）
        if token is not None:
            from ..auth.guard import check_tool_permission
            allowed, reason = check_tool_permission(token, name, audit)
            if not allowed:
                return f"❌ 鉴权拒绝：{reason}"

        try:
            schema = self._tools[name]
            valid_keys = set(schema.parameters.get("properties", {}).keys())
            filtered = {k: v for k, v in arguments.items() if k in valid_keys} if valid_keys else arguments
            from ..observability import tracer
            with tracer.span(f"tool:{name}", server=schema.server):
                return self._handlers[name](**filtered)
        except Exception as e:
            return f"❌ 工具 '{name}' 执行失败: {type(e).__name__}: {e}"

    def __len__(self) -> int:
        return len(self._tools)

    def __repr__(self) -> str:
        cats: dict[str, list[str]] = {}
        for name, s in self._tools.items():
            cats.setdefault(s.category, []).append(name)
        parts = [f"{cat}: {','.join(names)}" for cat, names in cats.items()]
        return f"ToolRegistry({len(self)}工具 | {'; '.join(parts)})"


def build_default_registry() -> ToolRegistry:
    """构建默认工具注册表（7 个工具：3 订单 + 3 资源 + 1 RAG）。

    RAG 工具 search_knowledge_base 用懒导入包装：建表时不加载重依赖，
    Agent 首次调用该工具才拉 jieba/chromadb/sentence_transformers。
    """
    r = ToolRegistry()
    # ---- 订单工具（order_server） ----
    r.register(
        "query_orders", "查询订单列表，可按状态和客户名筛选。状态：生产中/紧急/待排产/排期中/即将完成",
        {"type": "object", "properties": {
            "status": {"type": "string", "description": "订单状态筛选，空=全部"},
            "customer_name": {"type": "string", "description": "客户名模糊匹配，空=全部"},
        }},
        query_orders, "order", "order_server",
    )
    r.register(
        "get_order_detail", "获取单个订单的完整信息",
        {"type": "object", "properties": {"order_id": {"type": "string", "description": "订单编号，如 ORD001"}},
         "required": ["order_id"]},
        get_order_detail, "order", "order_server",
    )
    r.register(
        "get_production_status", "获取订单的当前生产环节和状态",
        {"type": "object", "properties": {"order_id": {"type": "string", "description": "订单编号，如 ORD001"}},
         "required": ["order_id"]},
        get_production_status, "order", "order_server",
    )
    # ---- 资源工具（resource_server） ----
    r.register(
        "query_inventory", "查询材料库存，可按材料名模糊搜索",
        {"type": "object", "properties": {"material_name": {"type": "string", "description": "材料名关键词，如'钛合金'，空=全部"}}},
        query_inventory, "resource", "resource_server",
    )
    r.register(
        "query_machine_load", "查询所有设备负载状态--哪些在运行、哪些空闲、预计何时释放",
        {"type": "object", "properties": {}},
        query_machine_load, "resource", "resource_server",
    )
    r.register(
        "query_customer", "查询客户信息--等级、信用分、历史延期率、行业",
        {"type": "object", "properties": {
            "customer_id": {"type": "string", "description": "客户编号，如 C001"},
            "customer_name": {"type": "string", "description": "客户名模糊匹配，如'深圳'"},
        }},
        query_customer, "resource", "resource_server",
    )
    # ---- RAG 工具（rag_server） ----
    # 用懒导入包装：建表时不加载 jieba/sentence_transformers，首次调用才拉 RAG 依赖
    def _search_kb(query: str, top_k: int = 3) -> str:
        from ..rag.retriever import search_knowledge_base
        return search_knowledge_base(query, top_k=top_k)

    r.register(
        "search_knowledge_base",
        "搜索合同知识库（混合检索+重排）。用于回答合同条款、延期记录、特殊约定等问题。"
        "例：'广州航天合同有什么特殊条款'、'深圳精密的延期记录'",
        {"type": "object", "properties": {
            "query": {"type": "string", "description": "检索问题，如'广州航天合同特殊条款'"},
            "top_k": {"type": "integer", "description": "返回片段数，默认3"},
        }, "required": ["query"]},
        _search_kb, "rag", "rag_server",
    )
    return r
