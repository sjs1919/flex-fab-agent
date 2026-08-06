"""demo 统一入口 -- 多 Agent 排产助手。

用法：
  python -m demo.main "今天先做哪些订单？"     # 单 Agent 模式处理查询
  python -m demo.main --chat                    # 多轮对话（状态持久化，重启可恢复）
  python -m demo.main --chat --thread <id>      # 续接指定会话
  python -m demo.main "..." --thread <id>       # 单次提问但恢复某会话上下文
  python -m demo.main --demo                    # 跑预设场景
  python -m demo.main --check                   # 地基自检（config/LLM/工具）
  python -m demo.main --mode multi "..."        # 多 Agent 模式（Step 3 接入）
"""
import sys
import uuid

from .config import available_providers
from .agents.single_agent import run_single_agent
from .tools.registry import build_default_registry
from .observability import tracer, cost_tracker

DEMO_SCENARIOS = [
    "今天先做哪些订单？帮我综合考虑交期紧迫度、客户等级、材料库存和设备负载情况，给出优先级排序。",
    "ORD001 能按时交付吗？帮我查一下这个订单的当前状态、所需材料和设备情况。",
    "现在有哪些紧急订单？哪些设备和材料是瓶颈？",
    "东莞模具厂的订单总体情况怎么样？信用如何？建议优先处理还是延后？",
    "帮我查一下 PEEK 材料的库存，如果不够，会影响哪些订单？",
]


def selfcheck():
    """Step 1 地基自检：config + LLM client + 工具层。"""
    from .core.llm_client import call_llm_simple
    print("=" * 60)
    print("地基自检")
    print("=" * 60)
    providers = available_providers()
    if not providers:
        print("❌ 没有可用的 provider！请检查 .env 配置")
        sys.exit(1)
    print(f"可用 Provider：{', '.join(p['name'] for p in providers)}")
    registry = build_default_registry()
    print(f"工具注册表：{registry}")
    print(f"\n查紧急订单：\n{registry.execute('query_orders', {'status': '紧急'})}")
    resp = call_llm_simple("你是调度助手，回答简洁。", "用 20 字说明排产关键因素。", max_tokens=80)
    print(f"\nLLM 回答：{resp.choices[0].message.content}")
    print("\n✅ 地基自检通过")


def main():
    args = sys.argv[1:]

    if "--check" in args:
        selfcheck()
        return

    # 解析参数
    mode = "single"       # 执行模式：single(默认) / multi(--mode multi，多 Agent) / demo(--demo，预设场景)
    chat = False          # 是否进多轮对话 REPL（--chat 触发，优先级最高，进了即 return）
    thread_id = None      # 会话 ID：--thread <id> 续接历史上下文；None=独立单次查询（可命中语义缓存）
    positional = []       # 位置参数桶：收集非 flag token，末尾 join 成查询文本
    i = 0
    while i < len(args):
        if args[i] == "--mode" and i + 1 < len(args):
            mode = args[i + 1]
            i += 2
        elif args[i] == "--demo":
            mode = "demo"
            i += 1
        elif args[i] == "--chat":
            chat = True
            i += 1
        elif args[i] == "--thread" and i + 1 < len(args):
            thread_id = args[i + 1]
            i += 2
        else:
            positional.append(args[i])
            i += 1

    print(f"可用 Provider：{', '.join(p['name'] for p in available_providers())}（自动降级）")

    if chat:
        _chat(thread_id or f"chat-{uuid.uuid4().hex[:12]}")
        return

    if mode == "demo":
        print(f"\n📋 预设场景（共 {len(DEMO_SCENARIOS)} 个）：\n")
        for idx, s in enumerate(DEMO_SCENARIOS, 1):
            print(f"  {idx}. {s}")
        print()
        try:
            choice = input("选择场景编号（回车=全部）> ").strip()
        except (EOFError, KeyboardInterrupt):
            choice = ""
        targets = [DEMO_SCENARIOS[int(choice) - 1]] if choice.isdigit() and 1 <= int(choice) <= len(DEMO_SCENARIOS) else DEMO_SCENARIOS
        for s in targets:
            _run_with_trace(run_single_agent, s)
        return

    query = " ".join(positional)
    if not query:
        print('\n用法：python -m demo.main "你的问题"  或  --chat  或  --demo  或  --check')
        print('多轮对话：--chat [--thread <会话id>]')
        return

    if mode == "multi":
        from .agents.supervisor import run_supervisor
        _run_with_trace(run_supervisor, query)
        return
    _run_with_trace(run_single_agent, query, thread_id=thread_id)


def _run_with_trace(fn, query, thread_id=None):
    """每轮查询：重置 tracer + cost -> 执行 -> 打印 trace + 费用摘要 -> 导出（观测层）。"""
    tracer.reset()
    cost_tracker.reset()
    if thread_id is not None:
        fn(query, thread_id=thread_id)
    else:
        fn(query)
    print()
    print(tracer.format_text())
    print(cost_tracker.format_text())
    tracer.flush()


def _chat(thread_id: str) -> None:
    """多轮对话 REPL：同一 thread_id 跨轮共享上下文（checkpointer 持久化）。"""
    print(f"\n💬 多轮会话 {thread_id}")
    print("输入问题开始对话（/exit 退出 · /new 新会话 · /switch <id> 切换会话）\n")
    while True:
        try:
            q = input("你> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not q:
            continue
        if q in ("/exit", "/quit"):
            break
        if q == "/new":
            thread_id = f"chat-{uuid.uuid4().hex[:12]}"
            print(f"\n💬 新会话 {thread_id}\n")
            continue
        if q.startswith("/switch "):
            thread_id = q.split(" ", 1)[1].strip()
            print(f"\n💬 切换到会话 {thread_id}\n")
            continue
        _run_with_trace(run_single_agent, q, thread_id=thread_id)
        print()


if __name__ == "__main__":
    main()
