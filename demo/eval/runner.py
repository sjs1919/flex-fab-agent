"""评估运行器 -- 遍历 ground_truth.json，逐个 case 跑 Agent，计算三层指标（R6 + 三层升级）。

三层指标：
  1. 工具层：工具调用 F1 / 完整性 / 订单召回 / min_tools_called（metrics.py）
  2. 轨迹层：路径效率 / 重试质量 / 循环检测（trajectory.py）
  3. 语义层：LLM-as-Judge faithfulness / answer_relevancy（judge.py）

用法：
  python -m demo.eval.runner           # 跑全部（单 Agent 模式，含 judge）
  python -m demo.eval.runner --case eval_001  # 跑单个
  python -m demo.eval.runner --mode multi      # 多 Agent 模式
  python -m demo.eval.runner --no-judge        # 跳过 LLM-as-Judge（评估提速/省钱）
  python -m demo.eval.runner --report          # 生成 HTML 报告
"""
import json
import sys
import time
from pathlib import Path

from ..agents.single_agent import run_single_agent
from ..observability import tracer, cost_tracker
from .metrics import compute_all_metrics
from .trajectory import compute_trajectory_score
from .trajectory_capture import rebuild_trajectory
from .judge import judge_semantic_quality, _extract_context

GROUND_TRUTH_PATH = Path(__file__).parent / "ground_truth.json"


def load_cases() -> list[dict]:
    """加载评估用例。"""
    if not GROUND_TRUTH_PATH.exists():
        print(f"⚠️  评估数据集不存在: {GROUND_TRUTH_PATH}")
        return []
    with open(GROUND_TRUTH_PATH, "r", encoding="utf-8") as f:
        return json.load(f).get("cases", [])


def _evaluate_single_case(case: dict, mode: str = "single", use_judge: bool = True) -> dict:
    """跑单个 case，产出三层指标。"""
    tracer.reset()
    cost_tracker.reset()
    print(f"\n{'=' * 60}\n 评估: {case['id']} — {case['scenario']}\n{'=' * 60}")
    print(f" 问题：{case['query']}")

    start = time.time()
    if mode == "multi":
        from ..agents.supervisor import run_supervisor
        result = run_supervisor(case["query"])
        answer = result.get("synthesis", "")
        tool_results = []
    else:
        result = run_single_agent(case["query"])
        answer = result.get("final_answer", "")
        tool_results = result.get("tool_results", [])
    elapsed = time.time() - start

    trace_summary = tracer.get_summary()
    cost_summary = cost_tracker.get_summary()

    # ---- 第 1 层：工具层（原有指标 + min_tools_called）----
    actual_tools = [tr["tool"] for tr in tool_results]
    tool_layer = compute_all_metrics(case, answer, actual_tools)

    # ---- 第 2 层：轨迹层 ----
    trajectory = rebuild_trajectory(trace_summary, tool_results)
    trajectory_layer = compute_trajectory_score(trajectory)

    # ---- 第 3 层：语义层（LLM-as-Judge）----
    semantic_layer = {"faithfulness": 0.0, "answer_relevancy": 0.0}
    if use_judge:
        context = _extract_context(tool_results)
        semantic_layer = judge_semantic_quality(case["query"], context, answer)

    # ---- 聚合 ----
    overall = round(
        tool_layer["overall_score"] * 0.5
        + trajectory_layer["trajectory_score"] * 0.3
        + (semantic_layer["faithfulness"] + semantic_layer["answer_relevancy"]) / 2 * 0.2,
        3,
    )

    case_result = {
        "case_id": case["id"],
        "scenario": case["scenario"],
        "query": case["query"],
        "answer_preview": answer[:150],
        "tool": tool_layer,
        "trajectory": trajectory_layer,
        "semantic": semantic_layer,
        "elapsed_s": round(elapsed, 2),
        "trace_id": tracer.trace_id,
        "token_usage": {
            "total_tokens": cost_summary.get("total_tokens", 0),
            "total_cost": cost_summary.get("total_cost", 0),
        },
        "overall_score": overall,
        "pass": overall >= 0.6,
    }
    return case_result


def run_eval(mode: str = "single", case_filter: str | None = None,
             use_judge: bool = True) -> list[dict]:
    """运行评估。mode: "single" | "multi"。"""
    cases = load_cases()
    if case_filter:
        cases = [c for c in cases if c["id"] == case_filter]
    if not cases:
        print("⚠️  没有评估用例可跑")
        return []

    results = []
    for i, case in enumerate(cases):
        case_result = _evaluate_single_case(case, mode=mode, use_judge=use_judge)
        results.append(case_result)
        status = "✅" if case_result["pass"] else "❌"
        print(f" {status} 评分: {case_result['overall_score']:.2f} | "
              f"工具: {case_result['tool']['overall_score']:.2f} | "
              f"轨迹: {case_result['trajectory']['trajectory_score']:.2f} | "
              f"语义: {(case_result['semantic']['faithfulness'] + case_result['semantic']['answer_relevancy']) / 2:.2f} | "
              f"耗时: {case_result['elapsed_s']:.1f}s")
        tracer.flush()

    return results


def print_summary(results: list[dict]) -> dict:
    """打印评估汇总报告。返回摘要 dict 供 CI 检查。"""
    if not results:
        return {"passed": 0, "total": 0, "avg_score": 0}
    passed = sum(1 for r in results if r["pass"])
    avg_score = sum(r["overall_score"] for r in results) / len(results)
    avg_tool = sum(r["tool"]["overall_score"] for r in results) / len(results)
    avg_traj = sum(r["trajectory"]["trajectory_score"] for r in results) / len(results)
    avg_sem = sum((r["semantic"]["faithfulness"] + r["semantic"]["answer_relevancy"]) / 2
                  for r in results) / len(results)
    avg_time = sum(r["elapsed_s"] for r in results) / len(results)
    total_cost = sum(r["token_usage"]["total_cost"] for r in results)

    print(f"\n{'=' * 60}\n 📊 评估汇总\n{'=' * 60}")
    print(f" 通过: {passed}/{len(results)} ({passed / len(results) * 100:.0f}%)")
    print(f" 综合评分: {avg_score:.2f}")
    print(f" 工具层: {avg_tool:.2f} | 轨迹层: {avg_traj:.2f} | 语义层: {avg_sem:.2f}")
    print(f" 平均耗时: {avg_time:.1f}s | 总费用: ¥{total_cost:.4f}")

    # 回归基线检查
    BASELINE_PASS = 7  # 期望至少 7/10 通过
    print(f"\n 回归检查：")
    if passed >= BASELINE_PASS:
        print(f"   ✅ 通过回归基线（{passed}/{len(results)} >= {BASELINE_PASS}/{len(results)}）")
    else:
        print(f"   ❌ 未通过回归基线（{passed}/{len(results)} < {BASELINE_PASS}/{len(results)}）")
        print(f"   → 请检查近期代码改动，确认是模型行为变化还是 bug 引入。")

    return {
        "passed": passed, "total": len(results), "avg_score": avg_score,
        "avg_tool": avg_tool, "avg_traj": avg_traj, "avg_sem": avg_sem,
    }


def main():
    """CLI 入口（python -m demo.eval.runner）。"""
    import argparse
    parser = argparse.ArgumentParser(description="Agent 评估运行器（三层：工具/轨迹/语义）")
    parser.add_argument("--case", type=str, help="只跑指定 case")
    parser.add_argument("--mode", type=str, default="single", choices=["single", "multi"])
    parser.add_argument("--no-judge", action="store_true", help="跳过 LLM-as-Judge 打分（评估提速）")
    parser.add_argument("--report", action="store_true", help="生成 HTML 评估报告")
    args = parser.parse_args()

    results = run_eval(mode=args.mode, case_filter=args.case, use_judge=not args.no_judge)
    summary = print_summary(results)
    if args.report:
        from .report import save_report
        save_report(results, summary)


if __name__ == "__main__":
    main()
