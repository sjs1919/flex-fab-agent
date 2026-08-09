"""跑全部 10 case 真实评估 + 生成 HTML 报告（独立脚本，绕开 CLI 管道问题）。"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

# 加 agent-training 根到 sys.path（demo 包需要父目录）
AGENT_TRAINING_ROOT = Path(__file__).resolve().parent.parent
if str(AGENT_TRAINING_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_TRAINING_ROOT))

from demo.eval.runner import load_cases, _evaluate_single_case, print_summary
from demo.eval.report import save_report
from demo.cache.llm_cache import clear


def main():
    clear()
    cases = load_cases()
    print(f"共 {len(cases)} case，开始跑...", flush=True)
    results = []
    for i, c in enumerate(cases):
        print(f"[{i + 1}/{len(cases)}] {c['id']}...", flush=True)
        r = _evaluate_single_case(c, mode="single", use_judge=True)
        results.append(r)
        sem = r["semantic"]
        print(f"  评分:{r['overall_score']:.2f} 工具:{r['tool']['overall_score']:.2f} "
              f"轨迹:{r['trajectory']['trajectory_score']:.2f} 语义:{sem.get('answer_relevancy', 0):.2f}", flush=True)
    print("全部跑完，生成报告...", flush=True)
    summary = print_summary(results)
    path = save_report(results, summary)
    print(f"REPORT:{path}", flush=True)


if __name__ == "__main__":
    main()
