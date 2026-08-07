"""评估运行器 -- 遍历 ground_truth.json，逐个 case 跑 Agent，计算指标（R6 缺陷修复）。

用法：
  python -m demo.eval.runner           # 跑全部（单 Agent 模式）
  python -m demo.eval.runner --case eval_001  # 跑单个
  python -m demo.eval.runner --mode multi      # 多 Agent 模式
"""
import json
import sys
import time
from pathlib import Path

from .metrics import compute_all_metrics

GROUND_TRUTH_PATH = Path(__file__).parent / "ground_truth.json"


def load_cases() -> list[dict]:
    """加载评估用例。"""
    if not GROUND_TRUTH_PATH.exists():
        print(f"⚠️  评估数据集不存在: {GROUND_TRUTH_PATH}")
        return []
    with open(GROUND_TRUTH_PATH, "r", encoding="utf-8") as f:
        return json.load(f).get("cases", [])


def run_eval(mode: str = "single", case_filter: str | None = None) -> list[dict]:
    """运行评估。

    Args:
        mode: "single" | "multi"
        case_filter: 只跑指定 case_id
    """
    # 延迟导入（避免循环导入）
    from ..agents.single_agent import run_single_agent
    from ..observability import tracer, cost_tracker

    cases = load_cases()
    if case_filter:
        cases = [c for c in cases if c["id"] == case_filter]
    if not cases:
        print("⚠️  没有评估用例可跑")
        return []

    results = []
    for i, case in enumerate(cases):
        tracer.reset()
        cost_tracker.reset()
        print(f"\n{'=' * 60}")
        print(f" 评估 [{i + 1}/{len(cases)}] : {case['id']} — {case['scenario']}")
        print(f" 问题：{case['query']}")
        print(f"{'=' * 60}")

        start = time.time()

        if mode == "multi":
            from ..agents.supervisor import run_supervisor
            result = run_supervisor(case["query"])
            answer = result.get("synthesis", "")
        else:
            answer = run_single_agent(case["query"])

        elapsed = time.time() - start
        trace_summary = tracer.get_summary()
        cost_summary = cost_tracker.get_summary()

        # 从 trace 中提取实际调用的工具名
        actual_tools: list[str] = []
        for span in trace_summary.get("spans", []):
            name = span.get("name", "")
            if name.startswith("tool:"):
                actual_tools.append(name.replace("tool:", ""))

        # 计算指标
        case_result = compute_all_metrics(case, answer, actual_tools)
        case_result["elapsed_s"] = round(elapsed, 2)
        case_result["trace_id"] = tracer.trace_id
        case_result["token_usage"] = {
            "total_tokens": cost_summary.get("total_tokens", 0),
            "total_cost": cost_summary.get("total_cost", 0),
        }
        case_result["pass"] = case_result["overall_score"] >= 0.6

        results.append(case_result)
        status = "✅" if case_result["pass"] else "❌"
        print(f" {status} 评分: {case_result['overall_score']:.2f} | "
              f"工具: {case_result['tool_call_accuracy']:.2f} | "
              f"完整性: {case_result['completeness_score']:.2f} | "
              f"耗时: {elapsed:.1f}s | token: {case_result['token_usage']['total_tokens']}")

        tracer.flush()

    return results


def print_summary(results: list[dict]) -> dict:
    """打印评估汇总报告。返回摘要 dict 供 CI 检查。"""
    if not results:
        return {"passed": 0, "total": 0, "avg_score": 0}
    passed = sum(1 for r in results if r["pass"])
    avg_score = sum(r["overall_score"] for r in results) / len(results)
    avg_tool = sum(r["tool_call_accuracy"] for r in results) / len(results)
    avg_time = sum(r["elapsed_s"] for r in results) / len(results)
    total_cost = sum(r["token_usage"]["total_cost"] for r in results)

    print(f"\n{'=' * 60}")
    print(f" 📊 评估汇总")
    print(f"{'=' * 60}")
    print(f" 通过: {passed}/{len(results)} ({passed / len(results) * 100:.0f}%)")
    print(f" 综合评分: {avg_score:.2f}")
    print(f" 工具调用准确率: {avg_tool:.2f}")
    print(f" 平均耗时: {avg_time:.1f}s")
    print(f" 总费用: ¥{total_cost:.4f}")
    print(f"\n 各 case 详情:")
    for r in results:
        status = "✅" if r["pass"] else "❌"
        print(f"   {status} {r['case_id']} ({r['scenario']}): "
              f"score={r['overall_score']:.2f} tool={r['tool_call_accuracy']:.2f}")

    # 回归基线检查
    BASELINE_PASS = 7  # 期望至少 7/10 通过
    print(f"\n 回归检查：")
    if passed >= BASELINE_PASS:
        print(f"   ✅ 通过回归基线（{passed}/{len(results)} >= {BASELINE_PASS}/{len(results)}）")
    else:
        print(f"   ❌ 未通过回归基线（{passed}/{len(results)} < {BASELINE_PASS}/{len(results)}）")
        print(f"   → 请检查近期代码改动，确认是模型行为变化还是 bug 引入。")

    return {"passed": passed, "total": len(results), "avg_score": avg_score}


def main():
    """CLI 入口（python -m demo.eval.runner）。"""
    import argparse
    parser = argparse.ArgumentParser(description="Agent 评估运行器")
    parser.add_argument("--case", type=str, help="只跑指定 case")
    parser.add_argument("--mode", type=str, default="single", choices=["single", "multi"])
    args = parser.parse_args()

    results = run_eval(mode=args.mode, case_filter=args.case)
    print_summary(results)


if __name__ == "__main__":
    main()
