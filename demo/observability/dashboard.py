"""B8 Dashboard 数据层（M5b）：KPI 快照 / 成本 / trace 的落库 + 只读查询。

三层职责：
  - 落库（写方唯一，对应 schema v3 三表）：
      simulator tick -> record_kpi_snapshot（kpi_metrics() 快照）
      api /ask       -> record_cost + record_trace（query 粒度）
  - 查询：kpi_history / cost_by_model / trace_summary -- 只读端点与静态 HTML
    共用（单一口径，验收条 74：KPI 与 query_kpi 同源）。
  - 兜底：render_static_html 生成离线 HTML（T5b.8，零 CDN）。

边界：cost.py / tracer.py 保持纯净（不 import 本模块，无 DB 依赖）；
本模块不 import 它们，只接收 get_summary() 产出的 dict。
"""
import json

from ..tools.data import get_connection, transaction


# ──────────────────────────────────────────────
# 落库（写方：simulator tick + api /ask）
# ──────────────────────────────────────────────

def record_kpi_snapshot(metrics: dict, sim_time, tenant_id: str = "default") -> int:
    """落一条 KPI 快照。metrics 为 kpi_metrics() 返回值，sim_time 为 tick 落点。返回快照 id。"""
    payload = json.dumps(metrics, default=str)
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO kpi_snapshot (sim_time, metrics_json, tenant_id) "
                "VALUES (%s, %s, %s)",
                (sim_time, payload, tenant_id))
            return cur.lastrowid


def record_cost(summary: dict, trace_id: str = "") -> int:
    """落一条成本记录。summary 为 cost_tracker.get_summary() 返回值。返回记录 id。

    by_model 用 .get 兜底：T5b.4 前该键不存在、零调用轮次也无数据，落空 dict。
    """
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO cost_record (trace_id, total_cost, total_tokens, total_calls, "
                "by_provider, by_model) VALUES (%s, %s, %s, %s, %s, %s)",
                (trace_id,
                 summary.get("total_cost", 0),
                 summary.get("total_tokens", 0),
                 summary.get("total_calls", 0),
                 json.dumps(summary.get("by_provider", {}), default=str),
                 json.dumps(summary.get("by_model", {}), default=str)))
            return cur.lastrowid


def record_trace(summary: dict, trace_id: str = "", max_spans: int = 50) -> int:
    """落一条 trace 记录。summary 为 tracer.get_summary() 返回值，span 明细截断到 max_spans。"""
    spans = summary.get("spans", [])[:max_spans]
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO trace_record (trace_id, total_ms, span_count, by_kind, spans) "
                "VALUES (%s, %s, %s, %s, %s)",
                (trace_id,
                 summary.get("total_ms", 0),
                 summary.get("span_count", 0),
                 json.dumps(summary.get("by_kind", {}), default=str),
                 json.dumps(spans, default=str)))
            return cur.lastrowid


# ──────────────────────────────────────────────
# 只读查询（读方：dashboard 端点 + 静态 HTML，单一口径）
# ──────────────────────────────────────────────

def kpi_history(limit: int = 500) -> list[dict]:
    """KPI 快照按 sim_time 升序（折线 x 轴方向），最新 limit 条。"""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, sim_time, metrics_json FROM kpi_snapshot "
                "ORDER BY sim_time DESC, id DESC LIMIT %s", (limit,))
            rows = cur.fetchall()
    finally:
        conn.close()
    return [{"id": r[0],
             "sim_time": r[1].strftime("%Y-%m-%d %H:%M:%S"),
             "metrics": json.loads(r[2])}
            for r in reversed(rows)]


def cost_by_model(limit: int = 500) -> dict:
    """成本记录倒序（最新在前）+ 跨记录按 model 聚合（calls/tokens/cost 求和）。

    聚合在服务端做一次，Vue 端点与静态 HTML 共用，避免两处重复实现。
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, trace_id, created_at, total_cost, total_tokens, total_calls, "
                "by_provider, by_model FROM cost_record ORDER BY id DESC LIMIT %s", (limit,))
            rows = cur.fetchall()
    finally:
        conn.close()
    items = [{"id": r[0], "trace_id": r[1],
              "created_at": r[2].strftime("%Y-%m-%d %H:%M:%S"),
              "total_cost": float(r[3]), "total_tokens": r[4], "total_calls": r[5],
              "by_provider": json.loads(r[6] or "{}"),
              "by_model": json.loads(r[7] or "{}")}
             for r in rows]
    agg: dict[str, dict] = {}
    for it in items:
        for model, st in it["by_model"].items():
            if model not in agg:
                agg[model] = {"calls": 0, "tokens": 0, "cost": 0.0}
            agg[model]["calls"] += st.get("calls", 0)
            agg[model]["tokens"] += st.get("tokens", 0)
            agg[model]["cost"] += st.get("cost", 0.0)
    for v in agg.values():
        v["cost"] = round(v["cost"], 6)
    return {"items": items, "by_model": agg}


def trace_summary(limit: int = 200) -> list[dict]:
    """trace 记录倒序（最新在前），摘要字段（spans 明细不随列表下发）。"""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, trace_id, created_at, total_ms, span_count, by_kind "
                "FROM trace_record ORDER BY id DESC LIMIT %s", (limit,))
            rows = cur.fetchall()
    finally:
        conn.close()
    return [{"id": r[0], "trace_id": r[1],
             "created_at": r[2].strftime("%Y-%m-%d %H:%M:%S"),
             "total_ms": float(r[3]), "span_count": r[4],
             "by_kind": json.loads(r[5] or "{}")}
            for r in rows]


def get_trace(trace_id: str) -> dict | None:
    """按 trace_id 取单条完整 trace（含 spans 明细）；不存在返回 None。"""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, trace_id, created_at, total_ms, span_count, by_kind, spans "
                "FROM trace_record WHERE trace_id=%s", (trace_id,))
            r = cur.fetchone()
    finally:
        conn.close()
    if not r:
        return None
    return {"id": r[0], "trace_id": r[1],
            "created_at": r[2].strftime("%Y-%m-%d %H:%M:%S"),
            "total_ms": float(r[3]), "span_count": r[4],
            "by_kind": json.loads(r[5] or "{}"),
            "spans": json.loads(r[6] or "[]")}


# ──────────────────────────────────────────────
# 静态 HTML 兜底（T5b.8，零 CDN，离线可看）
# ──────────────────────────────────────────────

def _svg_line(points: list[tuple[int, float]], width: int = 600, height: int = 200,
              y_max: float = 1.0) -> str:
    """极简内联 SVG 折线（points: (x 序号, y 值)），零依赖零外链。"""
    if not points:
        return '<svg width="600" height="200"><text x="10" y="100">暂无数据</text></svg>'
    n = len(points)
    xs = [20 + (width - 40) * i / max(n - 1, 1) for i in range(n)]
    ys = [height - 20 - (height - 40) * min(v / y_max, 1.0) for _, v in points]
    coords = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    return (f'<svg width="{width}" height="{height}" '
            f'style="border:1px solid #ccc">\n'
            f'<polyline points="{coords}" fill="none" stroke="#409eff" '
            f'stroke-width="2"/>\n</svg>')


def render_static_html(out_path: str = "dashboard.html") -> str:
    """把三块看板渲染成单文件 HTML（内联 SVG/表格，零 CDN，离线兜底）。"""
    import html as _html

    kpi = kpi_history()
    cost = cost_by_model()
    traces = trace_summary()

    # KPI 折线：准交率（0~1 -> y_max=1）
    rate_points = [(i, it["metrics"].get("on_time_rate") or 0.0)
                   for i, it in enumerate(kpi)]
    svg_rate = _svg_line(rate_points)

    rows_cost = "".join(
        f"<tr><td>{_html.escape(m)}</td><td>{v['calls']}</td>"
        f"<td>{v['tokens']}</td><td>¥{v['cost']:.6f}</td></tr>"
        for m, v in sorted(cost["by_model"].items())) or \
        '<tr><td colspan="4">暂无数据</td></tr>'
    rows_trace = "".join(
        f"<tr><td>{t['created_at']}</td><td>{_html.escape(t['trace_id'])}</td>"
        f"<td>{t['total_ms']:.1f} ms</td><td>{t['span_count']}</td>"
        f"<td>{_html.escape(', '.join(f'{k}×{v}' for k, v in t['by_kind'].items()))}</td></tr>"
        for t in traces) or '<tr><td colspan="5">暂无数据</td></tr>'

    doc = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>排产看板（离线快照）</title>
<style>
body{{font-family:sans-serif;margin:24px;color:#333}}
h2{{border-left:4px solid #409eff;padding-left:8px}}
table{{border-collapse:collapse;margin:8px 0}}
td,th{{border:1px solid #ddd;padding:4px 10px;font-size:14px}}
th{{background:#f5f7fa}}
</style></head><body>
<h1>排产看板（离线快照）</h1>
<h2>准交率走势（{len(kpi)} 个 tick 快照）</h2>
{svg_rate}
<h2>成本分模型</h2>
<table><tr><th>模型</th><th>调用数</th><th>tokens</th><th>费用</th></tr>{rows_cost}</table>
<h2>Trace 摘要（最近 {len(traces)} 条）</h2>
<table><tr><th>时间</th><th>trace_id</th><th>总耗时</th><th>span 数</th><th>类型分布</th></tr>{rows_trace}</table>
</body></html>"""
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(doc)
    return out_path


def main(argv: list[str] | None = None) -> int:
    """CLI：python -m demo.observability.dashboard --out dashboard.html。"""
    import argparse
    p = argparse.ArgumentParser(description="生成看板静态 HTML（离线兜底，零 CDN）")
    p.add_argument("--out", default="dashboard.html", help="输出文件路径")
    args = p.parse_args(argv)
    path = render_static_html(args.out)
    print(f"看板已生成：{path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
