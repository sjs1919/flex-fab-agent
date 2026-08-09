"""单页 HTML 评估报告生成。

生成一个自包含 HTML（内联 CSS，无外部依赖），当场可翻给面试官看。
"""
import html
from pathlib import Path


def _fmt(v: float) -> str:
    return f"{v:.2f}"


def _semantic_score(sem: dict) -> float:
    """语义分自适应（与 runner 一致）：有 context 用两指标均值，无 context 只用 relevancy。"""
    if sem.get("has_context"):
        return (sem["faithfulness"] + sem["answer_relevancy"]) / 2
    return sem["answer_relevancy"]


def _score_bar(value: float) -> str:
    """内联样式进度条。"""
    pct = int(max(0.0, min(1.0, value)) * 100)
    color = "#2e7d32" if value >= 0.6 else "#c62828"
    return f'<div class="bar"><div class="fill" style="width:{pct}%;background:{color}"></div></div>'


def render_html_report(results: list[dict], summary: dict | None = None) -> str:
    """渲染完整 HTML 报告。summary 为 print_summary 的返回（可选）。"""
    if not results:
        return "<html><body><p>暂无数据</p></body></html>"

    rows = []
    for r in results:
        sem = _semantic_score(r["semantic"])
        loop_flag = "🔴" if r["trajectory"].get("loop_detected") else "✅"
        rows.append(f"""
        <tr class="{'fail' if not r['pass'] else ''}">
            <td>{r['case_id']}</td>
            <td>{html.escape(r['scenario'])}</td>
            <td><div class="score">{_fmt(r['overall_score'])}</div>{_score_bar(r['overall_score'])}</td>
            <td>{_fmt(r['tool']['overall_score'])}</td>
            <td>{_fmt(r['trajectory']['trajectory_score'])} {loop_flag}</td>
            <td>{_fmt(sem)}</td>
            <td>{r['elapsed_s']:.1f}s</td>
        </tr>""")

    passed = sum(1 for r in results if r["pass"])
    total = len(results)
    avg = sum(r["overall_score"] for r in results) / total

    summary_html = ""
    if summary:
        summary_html = f"""
        <div class="summary-box">
            <div><strong>通过</strong><br>{passed}/{total}</div>
            <div><strong>综合评分</strong><br>{_fmt(avg)}</div>
            <div><strong>工具层均值</strong><br>{_fmt(summary.get('avg_tool', 0))}</div>
            <div><strong>轨迹层均值</strong><br>{_fmt(summary.get('avg_traj', 0))}</div>
            <div><strong>语义层均值</strong><br>{_fmt(summary.get('avg_sem') or 0)}</div>
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<title>Agent 评估报告</title>
<style>
body {{ font-family: -apple-system, 'Microsoft YaHei', sans-serif; margin: 2rem; color: #222; }}
h1 {{ font-size: 1.4rem; }}
.summary-box {{ display: flex; gap: 2rem; background: #f5f5f5; padding: 1rem 1.5rem;
                border-radius: 8px; margin: 1rem 0; }}
.summary-box div {{ text-align: center; }}
table {{ border-collapse: collapse; width: 100%; margin-top: 1rem; }}
th, td {{ border: 1px solid #ddd; padding: 8px 12px; text-align: left; font-size: 0.9rem; }}
th {{ background: #fafafa; }}
tr.fail {{ background: #fff3f3; }}
.score {{ font-weight: bold; }}
.bar {{ background: #eee; border-radius: 4px; height: 8px; margin-top: 4px; }}
.fill {{ height: 8px; border-radius: 4px; }}
</style>
</head>
<body>
<h1>📊 Agent 评估报告 — {total} 个场景</h1>
{summary_html}
<table>
<tr><th>Case</th><th>场景</th><th>综合</th><th>工具层</th><th>轨迹层</th><th>语义层</th><th>耗时</th></tr>
{''.join(rows)}
</table>
</body>
</html>"""


def save_report(results: list[dict], summary: dict | None = None,
                path: str | None = None) -> Path:
    """渲染并保存 HTML 报告。默认存到 demo/eval/reports/。"""
    out = Path(path) if path else Path(__file__).parent / "reports" / "eval_report.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_html_report(results, summary), encoding="utf-8")
    print(f"  📄 报告已生成: {out}")
    return out
