"""dashboard.py 落库/查询测试（M5b T5b.3，需 WSL MySQL 可用）。

覆盖：三张看板表的 record_* 写入 + 只读查询函数（kpi_history / cost_by_model /
trace_summary），span 落盘截断（max_spans 红线），空表返回空列表。
测试数据按 id 清理，不留残留。
"""
import json

from demo.observability import dashboard
from demo.tools.data import get_connection


def _cleanup(ids: dict[str, list[int]]) -> None:
    """按表名 -> id 列表清理测试数据。"""
    if not any(ids.values()):
        return
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            for table, pks in ids.items():
                for pk in pks:
                    cur.execute(f"DELETE FROM {table} WHERE id = %s", (pk,))
        conn.commit()
    finally:
        conn.close()


def test_record_kpi_snapshot_and_history():
    """KPI 快照写入 + kpi_history 升序返回、metrics 字典还原。"""
    ids = []
    try:
        m1 = {"on_time_rate": 0.8, "delay_total": 100.0, "generated_at": "2026-08-24 10:00:00"}
        m2 = {"on_time_rate": 0.9, "delay_total": 80.0, "generated_at": "2026-08-24 11:00:00"}
        ids.append(dashboard.record_kpi_snapshot(m1, "2026-08-24 10:00:00"))
        ids.append(dashboard.record_kpi_snapshot(m2, "2026-08-24 11:00:00"))
        hist = dashboard.kpi_history(limit=10)
        mine = [h for h in hist if h["id"] in ids]
        assert len(mine) == 2
        assert mine[0]["sim_time"] <= mine[1]["sim_time"]  # 升序（折线 x 轴）
        assert mine[0]["metrics"]["on_time_rate"] == 0.8
        assert mine[1]["metrics"]["delay_total"] == 80.0
    finally:
        _cleanup({"kpi_snapshot": ids})


def test_record_cost_and_by_model():
    """成本记录写入 + cost_by_model 返回倒序列表与跨记录 model 聚合。"""
    ids = []
    try:
        s1 = {"total_cost": 0.25, "total_tokens": 1000, "total_calls": 2,
              "by_provider": {"DeepSeek": {"calls": 2, "tokens": 1000, "cost": 0.25}},
              "by_model": {"deepseek-v4-flash": {"calls": 2, "tokens": 1000, "cost": 0.25}}}
        s2 = {"total_cost": 0.10, "total_tokens": 500, "total_calls": 1,
              "by_provider": {"Kimi(coding)": {"calls": 1, "tokens": 500, "cost": 0.10}},
              "by_model": {"deepseek-v4-flash": {"calls": 1, "tokens": 500, "cost": 0.10}}}
        ids.append(dashboard.record_cost(s1, trace_id="a" * 16))
        ids.append(dashboard.record_cost(s2, trace_id="b" * 16))
        result = dashboard.cost_by_model(limit=10)
        mine = [i for i in result["items"] if i["id"] in ids]
        assert len(mine) == 2
        assert mine[0]["id"] > mine[1]["id"]  # 倒序（最新在前）
        assert mine[0]["total_cost"] == 0.10 and mine[0]["trace_id"] == "b" * 16  # 最新在前
        assert mine[1]["total_cost"] == 0.25 and mine[1]["trace_id"] == "a" * 16
        agg = result["by_model"]["deepseek-v4-flash"]
        assert agg["calls"] == 3 and agg["tokens"] == 1500
        assert abs(agg["cost"] - 0.35) < 1e-9
    finally:
        _cleanup({"cost_record": ids})


def test_record_cost_without_by_model():
    """by_model 缺失（T5b.4 落地前 / 零 LLM 调用轮次）不报错，落空 dict。"""
    s = {"total_cost": 0.0, "total_tokens": 0, "total_calls": 0, "by_provider": {}}
    rid = None
    try:
        rid = dashboard.record_cost(s, trace_id="c" * 16)
        result = dashboard.cost_by_model(limit=10)
        mine = [i for i in result["items"] if i["id"] == rid]
        assert len(mine) == 1 and mine[0]["by_model"] == {}
    finally:
        _cleanup({"cost_record": [rid] if rid else []})


def test_record_trace_and_summary():
    """trace 记录写入 + trace_summary 返回摘要字段；span 明细截断到 max_spans。"""
    ids = []
    try:
        s1 = {"total_ms": 123.5, "span_count": 3, "by_kind": {"llm": 2, "tool": 1},
              "spans": [{"name": "llm:call", "ms": 100.0, "attrs": {}},
                        {"name": "tool:query", "ms": 20.0, "attrs": {}},
                        {"name": "llm:plan", "ms": 3.5, "attrs": {}}]}
        ids.append(dashboard.record_trace(s1, trace_id="d" * 16, max_spans=2))
        s2 = {"total_ms": 50.0, "span_count": 1, "by_kind": {"llm": 1},
              "spans": [{"name": "llm:x", "ms": 50.0, "attrs": {}}]}
        ids.append(dashboard.record_trace(s2, trace_id="e" * 16))
        rows = dashboard.trace_summary(limit=10)
        mine = [r for r in rows if r["id"] in ids]
        assert len(mine) == 2
        assert mine[0]["id"] > mine[1]["id"]  # 倒序
        assert mine[0]["trace_id"] == "e" * 16
        assert mine[1]["total_ms"] == 123.5
        assert mine[1]["by_kind"] == {"llm": 2, "tool": 1}
        # 截断验证：直接查落库的 spans 明细
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT spans FROM trace_record WHERE id = %s", (ids[0],))
                spans = json.loads(cur.fetchone()[0])
        finally:
            conn.close()
        assert len(spans) == 2  # 3 条截断到 max_spans=2
    finally:
        _cleanup({"trace_record": ids})


def test_empty_tables_return_empty_lists():
    """空查询路径：limit 内无数据时三函数均返回空（不抛异常）。"""
    assert isinstance(dashboard.kpi_history(limit=1), list)
    result = dashboard.cost_by_model(limit=1)
    assert isinstance(result["items"], list) and isinstance(result["by_model"], dict)
    assert isinstance(dashboard.trace_summary(limit=1), list)


# ---- render_static_html + CLI（T5b.8，离线兜底，零 CDN） ----

def test_render_static_html_creates_file(tmp_path):
    """落测试数据 -> 渲染 HTML：含 SVG 折线、成本/trace 表、零外链。"""
    ids = {"kpi_snapshot": [], "cost_record": [], "trace_record": []}
    try:
        for i, rate in enumerate((0.7, 0.85)):
            ids["kpi_snapshot"].append(dashboard.record_kpi_snapshot(
                {"on_time_rate": rate, "delay_total": 100 - 10 * i},
                f"2026-08-24 1{i}:00:00"))
        ids["cost_record"].append(dashboard.record_cost(
            {"total_cost": 0.25, "total_tokens": 1000, "total_calls": 2,
             "by_provider": {}, "by_model": {"m-x": {"calls": 2, "tokens": 1000, "cost": 0.25}}},
            trace_id="f" * 16))
        ids["trace_record"].append(dashboard.record_trace(
            {"total_ms": 99.0, "span_count": 2, "by_kind": {"llm": 1, "tool": 1},
             "spans": [{"name": "llm:a", "ms": 1.0, "attrs": {}}]}, trace_id="f" * 16))
        out = tmp_path / "dash.html"
        dashboard.render_static_html(str(out))
        html = out.read_text(encoding="utf-8")
        assert "<svg" in html and "polyline" in html  # 内联 SVG 折线
        assert "m-x" in html                       # 成本分模型表
        assert "span" in html                      # trace 表
        assert "http://" not in html and "https://" not in html  # 零 CDN/外链
    finally:
        _cleanup(ids)


def test_render_static_html_empty_db(tmp_path):
    """空库渲染不报错（空态提示而非崩溃）。"""
    out = tmp_path / "empty.html"
    dashboard.render_static_html(str(out))
    assert out.exists()
    assert "暂无数据" in out.read_text(encoding="utf-8")


def test_cli_writes_file(tmp_path):
    """CLI：python -m demo.observability.dashboard --out <path> 返回 0 并产出文件。"""
    out = tmp_path / "cli.html"
    rc = dashboard.main(["--out", str(out)])
    assert rc == 0 and out.exists()
