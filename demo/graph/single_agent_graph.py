"""单 Agent 的 LangGraph 状态图。

流程：
  analyze_intent -> select_and_execute -> evaluate_results
       ↑                                       │
       └──────── needs_more_data ──────────────┘
                                               │
                                          generate_answer -> END

对比 week4 多 Agent：单 Agent 一个节点做"查订单+查资源+综合判断"，
多 Agent 拆成 Supervisor + 审核 + 生产各司其职。

关键改动（vs 原 week3 langgraph_agent）：
  - 工具来源：原硬编码 TOOLS dict -> ToolRegistry（O(1) 查找 + 参数白名单）
  - LLM 调用：原本地 call_llm -> core.llm_client.call_llm（统一主备）
  - 节点通过闭包绑定 registry，build_single_agent_graph(registry) 工厂构造

R2 缺陷修复（2026-08-07）：generate_answer 集成 guardrails 输出护栏
R3 缺陷修复（2026-08-07）：evaluate_results 实现工具结果质量校验
R4 缺陷修复（2026-08-07）：select_and_execute 前自动检查上下文压缩
"""
import json
import re
from typing import Any

from langgraph.graph import END, StateGraph

from ..core.llm_client import call_llm
from ..graph.state import AgentState
from ..tools.registry import ToolRegistry

# B3 模型路由（v2 C7）：这些工具在场 => 排产推理场景，走 complex 强模型
_COMPLEX_TOOLS = frozenset({
    "run_scheduling", "query_load_assessment", "query_ctp",
    "query_order_tracking", "query_preprocess_load", "query_kpi",
})
# C2 排产上下文（v2 C2）：调过任一即视为已获排产表/负载/跟踪数据，evaluate 判数据充足
_SCHEDULE_CONTEXT_TOOLS = frozenset({
    "query_schedule", "query_load_assessment", "query_ctp",
    "query_order_tracking", "query_preprocess_load", "query_kpi",
})

# T5a.11：延期解释增强 — 从这些工具结果抽取延期清单注入综合指令
_DELAY_TOOLS = frozenset({
    "query_schedule", "query_load_assessment", "query_order_tracking", "query_kpi",
})
_DELAY_MARKERS = ("延期", "逾期", "超期", "延后", "预警", "⚠️", "红", "无法满足")
_DELAY_VERSION_RE = re.compile(r"排产版本\s*(\d+)")

# 缓存投毒根因修复（2026-08-24）：模型偶发把工具调用意图写成 DSML 标记文本
# （如 <|tool_calls|> / 尖括号调用名），同时 tool_calls 字段为空。若被当作
# 普通答案进入 final_answer 会污染语义缓存（eval 首跑 3/10 即此因）。识别后
# 注入纠错提示重试，而不是接受为答案。
# 2026-08-24 增补：模型还会输出全角竖线（U+FF5C）变体（｜tool_calls 家族），
# 检测前归一为 ASCII |；并补 ||DSML|| 双竖线包裹格式（||DSML||tool_calls 等）。
_TOOL_MARKUP_MARKERS = (
    "<|tool_calls|>", "<|tool_call|>", "<|/tool_calls|>",
    "<invoke ", "||DSML||", "||/DSML||",
)
_FULLWIDTH_BAR = chr(0xFF5C)


def _looks_like_tool_markup(text: str) -> bool:
    return any(m in text.replace(_FULLWIDTH_BAR, "|") for m in _TOOL_MARKUP_MARKERS)


def _sanitize_answer(text: str) -> str:
    """最终答案出口兜底：标记文本（未解析工具调用）替换为优雅提示，绝不透传给用户/缓存。"""
    if _looks_like_tool_markup(text):
        return _GRACEFUL_FALLBACK
    return text


class ToolMarkupOutput(Exception):
    """LLM 输出含未解析工具调用标记（DSML 文本）且 tool_calls 为空时抛出。

    调用方（select_and_execute / generate_answer）按需重试或兜底。
    """


_NUDGE = ("（系统提示：上一轮输出是未解析的工具调用标记文本，未产生任何工具调用。"
          "请改用标准 tool_calls 发起调用，或直接用中文回答。）")
# 汇总步专用纠错提示（2026-08-26）：本轮工具已不可用，不能沿用 _NUDGE 的
# 「改用标准 tool_calls」指引（会诱导模型再次输出工具调用语法），应明确禁止。
_SUMMARY_NUDGE = ("（系统提示：上一轮输出是未解析的工具调用标记文本。本轮为最终汇总，"
                  "工具已不可用，请勿输出任何工具调用语法，仅用中文输出综合结论。）")
_GRACEFUL_FALLBACK = "（抱歉，本次回答生成异常，请重试或换个问法。）"

# 循环守卫兜底前缀（2026-08-27 修复）：不再泄漏「检测到重复检索」内部诊断，改为
# 面向用户的简洁兜底。该前缀答案一律不得写入语义缓存（缓存投毒纵深防御，见 agents/single_agent.py）。
LOOP_GUARD_FALLBACK_PREFIX = "已多次检索未获得新的有效结果，基于已收集数据作答：\n"


def call_llm_agentic(messages, tools=None, **kwargs):
    """编排层公共 LLM 调用：检出 DSML 标记文本（tool_calls 空）即抛 ToolMarkupOutput。

    DSML 归属（2026-08-24 决策）：根因在推理服务（应服务端解析）；llm-client 保持
    纯 OpenAI 兼容不解析私有标记；兼容逻辑收敛在本编排层 wrapper，业务层无感知。
    此函数被 select_and_execute / generate_answer 共用，不散落到各节点。
    """
    resp = call_llm(messages, tools, **kwargs)
    msg = resp.choices[0].message
    if not msg.tool_calls and _looks_like_tool_markup(msg.content or ""):
        raise ToolMarkupOutput(msg.content or "")
    return resp


def _extract_delay_context(results: list[dict], max_lines: int = 15) -> str:
    """从排产工具结果抽取结构化延期数据：延期行（清单+天数）+ 排产版本号。

    只挑含延期标记的行（query_schedule/query_load_assessment 的延期清单、
    逾期预警、红区等），按出现顺序去重拼接，供 LLM 逐单解释延期原因。
    """
    lines: list[str] = []
    version = ""
    for tr in results:
        if tr.get("tool") not in _DELAY_TOOLS:
            continue
        text = tr.get("result", "") or ""
        m = _DELAY_VERSION_RE.search(text)
        if m:
            version = m.group(1)
        for ln in text.splitlines():
            stripped = ln.strip()
            if stripped and any(mk in stripped for mk in _DELAY_MARKERS) \
                    and stripped not in lines:
                lines.append(stripped)
    parts = [f"排产版本：{version}"] if version else []
    parts.extend(lines[:max_lines])
    return "\n".join(parts)


def build_single_agent_graph(registry: ToolRegistry, checkpointer=None):
    """构建单 Agent 状态图。registry 决定 Agent 可用哪些工具。"""

    tools_schema = registry.get_tool_defs()

    def analyze_intent(state: AgentState) -> AgentState:
        """分析用户意图（当前打印日志；生产可扩展为意图分类器路由）。"""
        user_msg = next((m["content"] for m in reversed(state["messages"]) if m["role"] == "user"), "")
        print(f"\n{'=' * 60}\n 用户提问：{user_msg}\n{'=' * 60}")
        return state

    def select_and_execute(state: AgentState) -> AgentState:
        """Agent 核心决策 + 执行：LLM 决策调哪些工具 -> 执行 -> 注入结果。

        R4：LLM 调用前自动检查上下文压缩。
        """
        # ---- R4 上下文压缩 ----
        from ..graph.context_compressor import compress_messages, should_compress
        if should_compress(state["messages"]):
            state["messages"] = compress_messages(state["messages"], call_llm)
            state["compression_count"] = state.get("compression_count", 0) + 1

        # ---- 原有逻辑 ----
        tool_names = {t.get("function", {}).get("name", "") for t in tools_schema}
        task_type = "complex" if _COMPLEX_TOOLS.intersection(tool_names) else "simple"
        try:
            response = call_llm_agentic(state["messages"], tools_schema, task_type=task_type)
        except ToolMarkupOutput:
            # 缓存投毒根因修复：识别到工具调用标记文本（tool_calls 为空）时不当作答案，
            # 注入纠错提示并 needs_retry 重试，避免标记进入 final_answer / 语义缓存。
            state["iteration"] += 1
            state["needs_retry"] = True
            state["messages"].append({"role": "user", "content": _NUDGE})
            return state
        msg = response.choices[0].message

        # LLM 未调工具 -> 直接返回文本（wrapper 已保证此处非标记文本）
        if not msg.tool_calls:
            state["messages"].append({"role": "assistant", "content": msg.content or ""})
            # 坑 22：纯文本轮也必须递增 iteration，否则 iteration 卡死、
            # needs_more 永真 -> should_continue 死循环（真实 RAG 场景暴露）
            state["iteration"] += 1
            # 模型给出了干净文本答案 -> 终止此前的重试标记（标记重试后干净文本应直接收尾）
            state["needs_retry"] = False
            return state

        # 执行每个 tool_call，记录 (tool_call, result) 一一对应关系
        executed: list[tuple[Any, str]] = []
        for tc in msg.tool_calls:
            tool_name = tc.function.name
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                args = {}

            schema = registry.get_schema(tool_name)
            server = schema.server if schema else "?"
            print(f" -> [{server}] {tool_name}({args})")

            result = registry.execute(tool_name, args)
            preview = result[:120].replace("\n", " ")
            print(f"   结果：{preview}...")
            state["tool_results"].append({"tool": tool_name, "arguments": args, "result": result})
            executed.append((tc, result))

        # 注入 assistant 消息（含 tool_calls 元数据）
        state["messages"].append({
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in msg.tool_calls
            ],
        })
        # 逐个注入 tool 消息（按 tool_call 一一对应执行结果，不按工具名取末条）。
        # 修复（2026-08-29）：单轮同工具多次调用（如 3× query_orders 不同 status）时，
        # 旧实现按工具名 matching[-1] 把最后一个结果（如「完成→未找到」）塞给全部 tool
        # 消息，汇总步 LLM 误读「待排队也空」，把 20 条待排队订单吞掉。
        for tc, result in executed:
            state["messages"].append({"role": "tool", "tool_call_id": tc.id, "content": result})

        state["iteration"] += 1
        return state

    def evaluate_results(state: AgentState) -> AgentState:
        """校验已收集的工具数据质量（R3 缺陷修复，不再是 noop）。

        检查：
          1. 每条 tool_result 非空且不以 ❌ 开头（工具执行错误）
          2. 已收集到至少一条订单数据和一条资源数据（排产场景的最低要求）
          3. 如果 LLM 没有调任何工具 -> 提醒 Agent 至少查一次
        """
        results = state.get("tool_results", [])
        iteration = state.get("iteration", 0)

        # 第一轮还没调工具 / 纯文本轮（LLM 直接作答、无工具结果）-> 跳过数据完整性校验。
        # 坑 22 修复：纯文本轮也递增 iteration 后，不能再依赖 iteration==0 跳过，
        # 否则纯文本答案被误判「数据不足」多绕一轮（StopIteration）。
        if iteration == 0 or not results:
            state["evaluation_notes"] = "首轮或纯文本作答，等待/直接输出"
            return state

        # ③ 筛选空结果即答案（2026-08-27 修复）：query_orders 带筛选条件且干净返回
        # 「未找到匹配的订单。」= 该筛选无匹配订单，直接据此作答。否则 evaluate 会以
        # 「数据不足」怂恿 LLM 继续补数据，不同参数的探索最终被循环守卫误判成循环
        # （坑：有没有订单已经打印完成？→ 3 次 query_orders → 原始 dump 进语义缓存）。
        for tr in results:
            if tr.get("tool") != "query_orders":
                continue
            args = tr.get("arguments") or {}
            if not any(args.values()):
                continue  # 无筛选条件（全量查询），空结果另有含义，不拦截
            if (tr.get("result") or "").strip() == "未找到匹配的订单。":
                state["evaluation_notes"] = "订单筛选无匹配（未找到），可直接据此作答"
                state["ready_for_answer"] = True
                state["needs_more"] = False
                state["needs_retry"] = False
                return state

        # 方案 3：循环检测——同一工具 + 相同参数「连续」出现 >=3 次才判定循环。
        # （坑 22：RAG 场景反复查同一数据，数据永远不足 -> needs_more 永真 -> 死循环。）
        # 2026-08-27 修复：旧实现用 Counter 全局计数，把不同参数的合理探索（如
        # query_orders(status=打印完成/完成/无过滤)）误判为循环，触发原始 dump 兜底
        # 并污染语义缓存。改为按（工具+参数）分组看连续长度，参数不同不计数。
        LOOP_THRESHOLD = 3  # 同工具 + 同参数连续 >=3 次判定循环
        from itertools import groupby
        seq = [(_tr.get("tool", ""),
                json.dumps(_tr.get("arguments", {}), sort_keys=True, ensure_ascii=False))
               for _tr in results]
        looped_tool = next((k for k, grp in groupby(seq)
                            if len(list(grp)) >= LOOP_THRESHOLD), None)
        if looped_tool:
            state["evaluation_notes"] = (f"检测到循环：工具 {looped_tool} 连续重复调用 "
                                         f"≥{LOOP_THRESHOLD} 次（相同参数），停止检索，基于已有数据作答")
            state["needs_more"] = False
            state["needs_retry"] = False
            state["ready_for_answer"] = True
            # 直接拼已有 tool 结果作答案，避免再调 LLM（LLM 可能仍返回 tool_call）
            parts = [f"- {tr.get('tool')}: {tr.get('result', '')[:200]}" for tr in results]
            state["final_answer"] = LOOP_GUARD_FALLBACK_PREFIX + "\n".join(parts)
            state["messages"].append({"role": "assistant", "content": state["final_answer"]})
            return state

        # 检查每条结果质量
        bad_results = []
        for tr in results:
            r = tr.get("result", "")
            if not r or r.startswith("❌"):
                bad_results.append(tr.get("tool", "?"))

        if bad_results:
            state["evaluation_notes"] = f"以下工具返回空或错误: {', '.join(bad_results)}"
            state["needs_retry"] = True
            return state

        # 检查数据完整性（排产场景至少需要订单 + 某类资源数据）
        tool_names = {tr.get("tool", "") for tr in results}
        has_order = any(t in tool_names for t in ["query_orders", "get_order_detail"])
        has_resource = any(t in tool_names for t in ["query_inventory", "query_machine_load", "query_customer"])
        has_schedule_context = any(t in tool_names for t in _SCHEDULE_CONTEXT_TOOLS)

        if has_schedule_context:
            # C2（v2）：已获取排产上下文（排产表/负载/CTP/跟踪/KPI）-> 数据充足，直接生成
            state["evaluation_notes"] = "已获取排产上下文数据，可以生成排产建议"
            state["ready_for_answer"] = True
            state["needs_more"] = False
            state["needs_retry"] = False
        elif not has_order:
            state["evaluation_notes"] = "尚未查询订单数据，建议先查订单"
            state["needs_more"] = True
        elif not has_resource:
            state["evaluation_notes"] = "已查订单，建议补充查询库存或设备数据"
            state["needs_more"] = True
        else:
            state["evaluation_notes"] = "数据已充足，可以生成排产建议"
            state["ready_for_answer"] = True
            # 数据充足时必须清掉前一轮的 needs_more/needs_retry 标记，
            # 否则 should_continue 会因残留的 needs_more 多绕一轮甚至死循环
            state["needs_more"] = False
            state["needs_retry"] = False

        return state

    def should_continue(state: AgentState) -> str:
        """条件边：判断是否继续调工具（R3 增强：加入 evaluate_results 的标记）。

        四种情况：
          ① 迭代≥5 强制结束（防死循环）
          ② evaluate_results 标记了 needs_retry -> 继续（重试失败的调用）
          ③ evaluate_results 标记了 needs_more -> 继续（补充更多数据）
          ④ 末条是 tool 结果 -> 继续
          ⑤ 末条是 assistant 文本（无 tool_calls）-> 生成最终答案
        """
        if state["iteration"] >= 5:
            return "generate_answer"

        # R3：evaluate_results 的智能判断
        # ready_for_answer（数据充足或检测到循环）-> 直接生成答案，不再走 tool 结果分支
        if state.get("ready_for_answer"):
            return "generate_answer"
        if state.get("needs_retry") and state["iteration"] < 4:
            return "select_and_execute"
        if state.get("needs_more") and state["iteration"] < 4:
            return "select_and_execute"

        last_msg = state["messages"][-1] if state["messages"] else {}
        if last_msg.get("role") == "tool":
            return "select_and_execute"
        if last_msg.get("role") == "assistant" and last_msg.get("tool_calls"):
            return "select_and_execute"
        return "generate_answer"

    def generate_answer(state: AgentState) -> AgentState:
        """综合所有数据生成最终调度建议（R2：集成 guardrails 输出护栏）。

        R2：LLM 输出经 guardrails pipeline 校验，阻断则重试最多 2 次。
        """
        last_msg = state["messages"][-1] if state["messages"] else {}
        # 上一条已是最终回复 -> 直接复用
        if last_msg.get("role") == "assistant" and last_msg.get("content") and not last_msg.get("tool_calls"):
            state["final_answer"] = _sanitize_answer(last_msg["content"])
            return state

        # 追加综合指令让 LLM 汇总（C2：已获取排产数据时引用排产结果作依据；
        # T5a.11 升级为结构化注入——带延期清单/天数/版本，而非只提示）
        delay_ctx = _extract_delay_context(state.get("tool_results", []))
        summary_lines = [
            "请基于以上所有工具查询结果，给出综合调度建议。",
            "必须包含：\n1. 关键发现（交期/客户/库存/设备）\n"
            "2. 今日优先排产订单（按优先级排序，列出订单号和原因）\n"
            "3. 可以延后的订单及原因",
        ]
        if delay_ctx:
            summary_lines.append(
                "【结构化延期数据（来自排产表/负载评估）】\n" + delay_ctx +
                "\n请逐单解释：哪些订单会延期、为什么（引用对应批次/排产版本），"
                "并给出可采取的对策。")
        else:
            summary_lines.append(
                "若已获取排产表/负载/CTP 数据，请引用版本号、批次、延期清单等"
                "排产结果作为排产依据。")
        summary_lines.append("用中文回答，格式清晰。")
        # 纵深防御（2026-08-26 方案 B）：主动禁止 DSML 标记语法，降低触发率
        # （_SUMMARY_NUDGE 为重试纠错，此处为正常 prompt 预防）
        summary_lines.append(
            "禁止输出 <|tool_calls|>/||DSML|| 等工具调用标记语法——本轮为最终汇总，"
            "不使用工具，仅用中文输出综合结论。")
        summary_prompt = {"role": "system", "content": "\n".join(summary_lines)}

        # ---- R2 护栏集成：最多重试 2 次 ----
        from ..guardrails import run_guardrails

        MAX_RETRIES = 2
        for retry in range(MAX_RETRIES + 1):
            try:
                response = call_llm_agentic(state["messages"] + [summary_prompt],
                                            task_type="complex")
                answer = response.choices[0].message.content or ""
            except ToolMarkupOutput:
                # 汇总步标记文本：与 select_and_execute 对齐，注入纠错提示重试，
                # 而不是直接降级为死胡同兜底（2026-08-26 复现：工具数据全拿到，
                # 汇总步模型偶发输出 DSML 标记文本 -> 用户只看到兜底道歉）。
                if retry < MAX_RETRIES:
                    state["messages"].append({"role": "user", "content": _SUMMARY_NUDGE})
                    print(f"  ⚠️  [汇总步标记文本] 第 {retry + 1} 次重试...")
                    continue
                # 重试耗尽仍产出标记文本 -> 优雅提示，不进入答案/缓存
                answer = _GRACEFUL_FALLBACK
                break
            except Exception as e:
                # 兜底：LLM 失败时返回原始工具数据
                answer = f"调度建议生成失败：{e}\n\n已收集的工具数据：\n"
                for tr in state["tool_results"]:
                    answer += f"\n--- {tr['tool']} ---\n{tr['result'][:300]}"
                break  # LLM 调用失败，跳过护栏直接返回兜底

            # 护栏检查
            gr = run_guardrails(answer, context={"mode": "scheduling"})
            if gr.is_valid:
                answer = gr.text
                break
            else:
                if retry < MAX_RETRIES:
                    print(f"  ⚠️  [护栏拦截] {gr.blocked_by}，第 {retry + 1} 次重试...")
                    # 在 prompt 中追加护栏反馈，让 LLM 修正
                    state["messages"].append({
                        "role": "system",
                        "content": f"上次输出被护栏拦截: {gr.blocked_by}。请修改后重新输出。"
                    })
                else:
                    # 多次重试仍不通过 -> 降级返回安全版本
                    answer = (f"抱歉，生成排产建议时遇到问题（{gr.blocked_by}）。\n"
                              "请稍后重试或联系管理员。")

        state["final_answer"] = _sanitize_answer(answer)
        state["messages"].append({"role": "assistant", "content": answer})
        return state

    # ---- 组装状态图 ----
    graph = StateGraph(AgentState)
    graph.add_node("analyze_intent", analyze_intent)
    graph.add_node("select_and_execute", select_and_execute)
    graph.add_node("evaluate_results", evaluate_results)
    graph.add_node("generate_answer", generate_answer)
    graph.set_entry_point("analyze_intent")
    graph.add_edge("analyze_intent", "select_and_execute")
    graph.add_edge("select_and_execute", "evaluate_results")
    graph.add_conditional_edges("evaluate_results", should_continue, {
        "select_and_execute": "select_and_execute",
        "generate_answer": "generate_answer",
    })
    graph.add_edge("generate_answer", END)
    return graph.compile(checkpointer=checkpointer)
