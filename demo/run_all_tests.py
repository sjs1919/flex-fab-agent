"""demo 一键自动化测试脚本。

用法：
  python run_all_tests.py              # 全量单测 + 集成测试
  python run_all_tests.py --eval       # 全量单测 + 三层评估（真实 LLM，需 .env key）
  python run_all_tests.py --report     # 全量单测 + 三层评估 + 生成 HTML 报告
  python run_all_tests.py --no-judge   # 评估时跳过 LLM-as-Judge（省钱/提速）

流程：
  1. pytest 全量单元测试 + 集成测试（mock LLM，不花钱）
  2. （可选 --eval）跑三层评估（真实 Agent + 真实 LLM）
  3. （可选 --report）生成单页 HTML 报告
"""
import argparse
import subprocess
import sys
from pathlib import Path

# Windows 控制台默认 GBK，无法输出 emoji，重配为 UTF-8
for _stream in (sys.stdin, sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8")
        except Exception:
            pass

DEMO_ROOT = Path(__file__).resolve().parent
PYTHON = sys.executable


def run_unit_tests() -> bool:
    """跑全量 pytest（单测 + 集成测试）。"""
    print("\n" + "=" * 60)
    print(" 步骤 1/3：pytest 全量测试（mock LLM，零成本）")
    print("=" * 60)
    result = subprocess.run([PYTHON, "-m", "pytest", "-v"], cwd=DEMO_ROOT)
    return result.returncode == 0


def run_eval(use_judge: bool) -> bool:
    """跑三层评估（真实 Agent + 真实 LLM）。"""
    print("\n" + "=" * 60)
    print(" 步骤 2/3：三层评估（工具/轨迹/语义）")
    print("=" * 60)
    cmd = [PYTHON, "-m", "demo.eval.runner"]
    if not use_judge:
        cmd.append("--no-judge")
    result = subprocess.run(cmd, cwd=DEMO_ROOT)
    return result.returncode == 0


def generate_report() -> bool:
    """生成 HTML 报告。"""
    print("\n" + "=" * 60)
    print(" 步骤 3/3：生成 HTML 评估报告")
    print("=" * 60)
    # 复用 runner 的 --report 逻辑
    result = subprocess.run(
        [PYTHON, "-m", "demo.eval.runner", "--report", "--no-judge"],
        cwd=DEMO_ROOT,
    )
    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser(description="demo 一键自动化测试")
    parser.add_argument("--eval", action="store_true", help="跑三层评估（真实 LLM）")
    parser.add_argument("--no-judge", action="store_true", help="评估跳过 LLM-as-Judge")
    parser.add_argument("--report", action="store_true", help="生成 HTML 报告")
    args = parser.parse_args()

    # 1. 单元测试（必须过）
    ok = run_unit_tests()
    if not ok:
        print("\n❌ 单元测试失败，中止。")
        sys.exit(1)
    print("\n✅ 单元测试全部通过")

    # 2. 可选：三层评估
    if args.eval:
        if not run_eval(use_judge=not args.no_judge):
            print("\n⚠️ 评估完成但回归基线未达成（详见上方输出）")

    # 3. 可选：报告
    if args.report:
        if not generate_report():
            print("\n⚠️ 报告生成失败")

    print("\n" + "=" * 60)
    print(" 🎉 demo 自动化测试完成")
    print("=" * 60)


if __name__ == "__main__":
    main()
