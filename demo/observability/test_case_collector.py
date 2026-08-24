"""M6 T6.4：case_collector 单元测试（分类/落盘/开关/采样/回写）。

cases.jsonl 落 tmp_path（monkeypatch 模块 CASES_PATH），不污染真实 DATA_DIR。
"""
import json

import pytest

import demo.observability.case_collector as cc


@pytest.fixture
def tmp_cases(tmp_path, monkeypatch):
    """case 文件指向 tmp，开关默认全开（隔离 system_config 与 DB）。"""
    path = tmp_path / "cases.jsonl"
    monkeypatch.setattr(cc, "CASES_PATH", path)

    def fake_config(category, key, default=""):
        return {"case_collection_enabled": "on", "sample_rate": "1.0",
                "judge_enabled": "off"}.get(key, default)

    monkeypatch.setattr(cc, "get_config", fake_config)
    return path


# ---- classify 分类规则 ----

def test_classify_empty():
    assert cc.classify("") == "empty"
    assert cc.classify("   \n\t ") == "empty"


def test_classify_chitchat():
    assert cc.classify("你好") == "chitchat"
    assert cc.classify(" 谢谢！ ") == "chitchat"
    assert cc.classify("再见") == "chitchat"


def test_classify_normal():
    assert cc.classify("查询订单 ORD001 的风险") == "normal"
    assert cc.classify("你好，请帮我评估产能") == "normal"  # 含寒暄词但非纯寒暄


# ---- 落盘 + 读回 ----

def test_record_case_persists(tmp_cases):
    ok = cc.record_case(query="查询订单", answer="答", tools=["query_orders"],
                        trace_id="t1")
    assert ok is True
    rows = [json.loads(l) for l in tmp_cases.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    r = rows[0]
    assert r["trace_id"] == "t1" and r["query"] == "查询订单"
    assert r["type"] == "normal" and r["good"] is None
    assert r["tools"] == ["query_orders"] and r["judge"] == {}
    assert r["created_at"]


def test_load_cases_filters(tmp_cases):
    cc.record_case("查询订单", "a", [], "t1")            # normal
    cc.record_case("你好", "b", [], "t2")                 # chitchat
    cc.record_case("查询库存", "c", [], "t3")             # normal
    all_rows = cc.load_cases()
    assert [r["trace_id"] for r in all_rows] == ["t1", "t2", "t3"]
    normals = cc.load_cases(case_type="normal")
    assert [r["trace_id"] for r in normals] == ["t1", "t3"]
    limited = cc.load_cases(limit=2)
    assert [r["trace_id"] for r in limited] == ["t2", "t3"]  # 取最新 N 条


def test_record_case_disabled(tmp_cases, monkeypatch):
    monkeypatch.setattr(cc, "get_config",
                        lambda c, k, d="": "off" if k == "case_collection_enabled" else d)
    assert cc.record_case("查询订单", "a", [], "t1") is False
    assert not tmp_cases.exists()


def test_record_case_sample_rate_zero(tmp_cases, monkeypatch):
    monkeypatch.setattr(cc, "get_config",
                        lambda c, k, d="": "0.0" if k == "sample_rate" else d)
    assert cc.record_case("查询订单", "a", [], "t1") is False
    assert not tmp_cases.exists()


# ---- 标注 / 回写 ----

def test_label_case_normal_only(tmp_cases):
    cc.record_case("查询订单", "a", [], "t1")
    cc.record_case("你好", "b", [], "t2")
    assert cc.label_case("t2", True) is False, "chitchat 不可标注"
    assert cc.label_case("t1", True) is True
    rows = {r["trace_id"]: r for r in cc.load_cases()}
    assert rows["t1"]["good"] is True and rows["t2"]["good"] is None


def test_label_case_missing(tmp_cases):
    assert cc.label_case("nope", True) is False


def test_attach_judge_and_rerun(tmp_cases):
    cc.record_case("查询订单", "a", [], "t1")
    assert cc.attach_judge("t1", {"score": 4.5, "pass": True}) is True
    assert cc.attach_rerun("t1", {"trace_id": "t1-new", "answer": "新答"}) is True
    r = cc.load_cases()[0]
    assert r["judge"] == {"score": 4.5, "pass": True}
    assert r["rerun"]["trace_id"] == "t1-new"
    assert cc.attach_judge("nope", {}) is False
