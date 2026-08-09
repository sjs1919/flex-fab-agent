"""回测运行器 -- 用 Agent 复盘历史延期案例，对照人工结论。

用法：
  python -m demo.backtest.runner           # 跑全部 5 个场景
  python -m demo.backtest.runner --case bt_001  # 跑单个

流程：
  1. 加载历史延期复盘场景（scenarios.py）
  2. 跑单 Agent 对每个场景提问（真实 LLM，查工具）
  3. score_backtest 评估覆盖度（命中关键要点 / 触发禁止词）
  4. 汇总报告 + 回归基线
"""
import argparse
import sys
from pathlib import Path

from .scenarios import load_scenarios, score_backtest

BASELINE_COVERAGE = 0.6  # 期望平均覆盖度 >= 0.6


def _run_case(scenario: dict) -> dict:
    """跑单个回测场景。返回答案 + 覆盖度。"""
    from ..agents.single_agent import run_single_agent

    print(f"\n{'=' * 60}")
    print(f" 回测: {scenario['id']} — {scenario['title']}")
    print(f"{'=' * 60}")
    print(f" 提问：{scenario['query'][:80]}...")

    result = run_single_agent(scenario["query"])
    answer = result.get("final_answer", "")
    tools = [tr["tool"] for tr in result.get("tool_results", [])]

    score = score_backtest(answer, scenario)
    print(f" 覆盖: {score['hits']}/{score['total']} ({score['coverage']:.0%})"
          f"{' | ⚠️ 含禁止词' if score['forbidden_hit'] else ''}")
    print(f" 工具调用: {tools}")

    return {
        "id": scenario["id"],
        "title": scenario["title"],
        "answer_preview": answer[:200],
        "tools_used": tools,
        "coverage": score,
    }


def run_backtest(case_filter: str | None = None) -> list[dict]:
    """跑全部回测场景。"""
    scenarios = load_scenarios()
    if case_filter:
        scenarios = [s for s in scenarios if s["id"] == case_filter]
    if not scenarios:
        print("⚠️  没有回测场景")
        return []

    results = []
    for s in scenarios:
        results.append(_run_case(s))
    return results


def print_summary(results: list[dict]) -> dict:
    """打印汇总报告。返回摘要供 CI 检查。"""
    if not results:
        return {"avg_coverage": 0, "passed": 0, "total": 0}
    avg = sum(r["coverage"]["coverage"] for r in results) / len(results)
    passed = sum(1 for r in results if r["coverage"]["coverage"] >= BASELINE_COVERAGE)

    print(f"\n{'=' * 60}")
    print(f" 📊 回测汇总")
    print(f"{'=' * 60}")
    print(f" 场景通过: {passed}/{len(results)}（覆盖度 >= {BASELINE_COVERAGE:.0%}）")
    print(f" 平均覆盖度: {avg:.0%}")
    for r in results:
        status = "✅" if r["coverage"]["coverage"] >= BASELINE_COVERAGE else "❌"
        print(f"   {status} {r['id']} ({r['title']}): "
              f"覆盖 {r['coverage']['hits']}/{r['coverage']['total']} = {r['coverage']['coverage']:.0%}")

    if avg >= BASELINE_COVERAGE:
        print(f"\n ✅ 通过回测基线（平均覆盖度 {avg:.0%} >= {BASELINE_COVERAGE:.0%}）")
    else:
        print(f"\n ❌ 未通过回测基线（平均覆盖度 {avg:.0%} < {BASELINE_COVERAGE:.0%}）")

    return {"avg_coverage": avg, "passed": passed, "total": len(results)}


def main():
    parser = argparse.ArgumentParser(description="历史场景回测（Agent 复盘验证）")
    parser.add_argument("--case", type=str, help="只跑指定场景")
    args = parser.parse_args()

    results = run_backtest(args.case)
    print_summary(results)


if __name__ == "__main__":
    main()
