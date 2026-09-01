"""operation_log 模块测试（需 WSL MySQL 可用）。

覆盖：record 写入 / query 分页与各筛选维度 / classify_request 分流与排除。
测试数据按 id 清理，不留残留。
"""
import json
import time

from flex_fab_agent.observability import operation_log
from flex_fab_agent.tools.data import get_connection


def _cleanup(ids: list[int]) -> None:
    if not ids:
        return
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            for pk in ids:
                cur.execute("DELETE FROM operation_log WHERE id = %s", (pk,))
        conn.commit()
    finally:
        conn.close()


def test_record_and_query():
    ids = []
    try:
        ids.append(operation_log.record_operation(
            "manual", "测试动作", "ok", summary="摘要A", relate_id="1",
            trace_id="abcdef1234567890"))
        ids.append(operation_log.record_operation(
            "debug", "调试重跑", "fail", summary="摘要B"))
        page = operation_log.query_operations(page=1, page_size=10)
        mine = [i for i in page["items"] if i["id"] in ids]
        assert len(mine) == 2
        assert page["total"] >= 2
    finally:
        _cleanup(ids)


def test_query_filter_category():
    ids = []
    try:
        ids.append(operation_log.record_operation("manual", "甲", "ok", "m"))
        ids.append(operation_log.record_operation("simulator", "乙", "ok", "s"))
        q = operation_log.query_operations(category="simulator", page_size=50)
        assert all(i["category"] == "simulator" for i in q["items"])
        assert any(i["id"] == ids[1] for i in q["items"])
    finally:
        _cleanup(ids)


def test_query_keyword():
    ids = []
    try:
        ids.append(operation_log.record_operation("manual", "排产加载", "ok", "摘要", trace_id="trace001"))
        ids.append(operation_log.record_operation("debug", "其他", "ok", "无关"))
        ids.append(operation_log.record_operation("manual", "无关动作", "ok", "特定摘要X"))
        q = operation_log.query_operations(keyword="trace001", page_size=50)
        assert any(i["id"] == ids[0] for i in q["items"])
        q2 = operation_log.query_operations(keyword="排产", page_size=50)
        assert any(i["id"] == ids[0] for i in q2["items"])
        q3 = operation_log.query_operations(keyword="特定摘要X", page_size=50)
        assert any(i["id"] == ids[2] for i in q3["items"])
    finally:
        _cleanup(ids)


def test_record_detail_serialize():
    ids = []
    try:
        pk = operation_log.record_operation(
            "manual", "详情序列化", "ok", "detail 测试", detail={"a": 1, "b": "中文"})
        ids.append(pk)
        q = operation_log.query_operations(page_size=50)
        mine = [i for i in q["items"] if i["id"] == pk]
        assert len(mine) == 1
        assert json.loads(mine[0]["detail_json"]) == {"a": 1, "b": "中文"}
    finally:
        _cleanup(ids)


def test_query_page_out_of_range():
    ids = []
    try:
        pk = operation_log.record_operation("manual", "分页越界", "ok", "分页测试")
        ids.append(pk)
        q = operation_log.query_operations(page=99999, page_size=10)
        assert q["items"] == []
        assert q["total"] >= 1
    finally:
        _cleanup(ids)


def test_query_time_range():
    ids = []
    try:
        ids.append(operation_log.record_operation("manual", "早", "ok", "早"))
        q0 = operation_log.query_operations(page_size=50)
        t_a = [i for i in q0["items"] if i["id"] == ids[0]][0]["real_time"]
        time.sleep(1.1)
        ids.append(operation_log.record_operation("manual", "晚", "ok", "晚"))
        # start=t_a：A(real_time==t_a) 与 B(real_time>t_a) 都命中
        q_both = operation_log.query_operations(start=t_a, page_size=50)
        assert any(i["id"] == ids[0] for i in q_both["items"])
        assert any(i["id"] == ids[1] for i in q_both["items"])
        # end=t_a：仅 A 命中，B 晚于 t_a 被排除
        q_early = operation_log.query_operations(end=t_a, page_size=50)
        assert any(i["id"] == ids[0] for i in q_early["items"])
        assert not any(i["id"] == ids[1] for i in q_early["items"])
    finally:
        _cleanup(ids)


def test_classify_request():
    assert operation_log.classify_request("POST", "/debug/rerun/123") == ("debug", "调试重跑")
    assert operation_log.classify_request("GET", "/debug/cases") == ("debug", "调试用例")
    assert operation_log.classify_request("POST", "/schedule/load") == ("manual", "手动排产加载")
    assert operation_log.classify_request("POST", "/ask") == ("manual", "智能问答")
    assert operation_log.classify_request("PUT", "/resources/personnel/P001/status") == \
        ("manual", "资源操作")
    assert operation_log.classify_request("GET", "/") is None
    assert operation_log.classify_request("GET", "/health") is None
    assert operation_log.classify_request("GET", "/logs") is None
    assert operation_log.classify_request("GET", "/assets/index-abc.js") is None
    assert operation_log.classify_request("GET", "/debug/admin-token") is None
    assert operation_log.classify_request("GET", "/unknown/path") is None
