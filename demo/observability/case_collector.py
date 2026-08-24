"""调试台 case 收集器（M6 T6.4 / v2 G1）。

/ask 结束后旁路落盘 cases.jsonl（DATA_DIR 下运行时生成，gitignore）：
  - classify(query)：empty（空白）/ chitchat（纯寒暄词）/ normal（业务问句）
  - record_case(query, answer, tools, trace_id)：开关 + 采样判定后 JSONL 追加
  - load_cases / label_case / attach_judge / attach_rerun：调试台端点读写

设计要点：
  - 纯数据层：不 import api/agents；由 /ask 旁路调用（失败不改变主响应）
  - 开关走 system_config（类别「调试台」）：case_collection_enabled 默认 on、
    sample_rate 默认 1.0（生产 0.1）、judge_enabled 默认 off
  - JSONL 追加写 + threading.Lock 防并发交错；回写用全量读改写（demo 规模）
"""
import json
import random
import threading
from datetime import datetime

from ..config import DATA_DIR, get_config

CASES_PATH = DATA_DIR / "cases.jsonl"

# 纯寒暄词表（classify 用，命中且整句仅寒暄 -> chitchat）
CHITCHAT_WORDS = {
    "你好", "您好", "你们好", "hi", "hello", "哈喽",
    "谢谢", "多谢", "辛苦了", "感谢",
    "再见", "拜拜",
    "早上好", "上午好", "中午好", "下午好", "晚上好",
}

_WRITE_LOCK = threading.Lock()

# 标点剥离后再比对词表（"谢谢！" 也算寒暄）
_STRIP_CHARS = "！？。，,．.、~～!?\t \n"


def classify(query: str) -> str:
    """三分类：empty / chitchat / normal。"""
    q = (query or "").strip()
    if not q:
        return "empty"
    bare = q.strip(_STRIP_CHARS)
    return "chitchat" if bare and bare.lower() in CHITCHAT_WORDS else "normal"


def _collection_enabled() -> bool:
    v = get_config("调试台", "case_collection_enabled", "on").strip().lower()
    return v not in ("off", "0", "false", "no")


def _sample_rate() -> float:
    try:
        rate = float(get_config("调试台", "sample_rate", "1.0"))
    except ValueError:
        return 1.0
    return min(max(rate, 0.0), 1.0)


def record_case(query: str, answer: str, tools, trace_id: str, judge=None) -> bool:
    """落一条 case。开关关 / 采样未命中 -> False（不落盘）。"""
    if not _collection_enabled():
        return False
    if random.random() >= _sample_rate():
        return False
    record = {
        "trace_id": trace_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "query": query,
        "answer": answer,
        "type": classify(query),
        "good": None,  # 三态：true/false/null 未标注（仅 normal 可标注）
        "tools": list(tools or []),
        "judge": judge or {},
    }
    with _WRITE_LOCK:
        with open(CASES_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return True


def load_cases(case_type: str | None = None, good=None,
               limit: int | None = None) -> list[dict]:
    """读回 case 列表（按时间正序；limit 取最新 N 条）。good 过滤需含三态。"""
    if not CASES_PATH.exists():
        return []
    rows: list[dict] = []
    with open(CASES_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # 跳过坏行（半写入等），不炸整个读端点
    if case_type is not None:
        rows = [r for r in rows if r.get("type") == case_type]
    if good is not None:
        g = None if good in ("null", "", None) else _to_bool(good)
        rows = [r for r in rows if r.get("good") is g]
    if limit is not None:
        rows = rows[-limit:]
    return rows


def _to_bool(v) -> bool:
    return v if isinstance(v, bool) else str(v).strip().lower() in ("true", "1", "yes")


def _rewrite(update) -> bool:
    """全量读改写（demo 规模可接受）。update(row) 返回 True 表示已修改。"""
    rows = load_cases()
    if not any(update(r) for r in rows):
        return False
    with _WRITE_LOCK:
        with open(CASES_PATH, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return True


def label_case(trace_id: str, good: bool) -> bool:
    """人工标注 good/bad，仅 normal case 生效。"""
    return _rewrite(lambda r: (trace_id == r.get("trace_id")
                               and r.get("type") == "normal"
                               and r.__setitem__("good", bool(good)) is None))


def attach_judge(trace_id: str, payload: dict) -> bool:
    """judge 分数写回 case.judge。"""
    return _rewrite(lambda r: trace_id == r.get("trace_id")
                    and r.__setitem__("judge", payload) is None)


def attach_rerun(trace_id: str, payload: dict) -> bool:
    """重跑结果写回 case.rerun。"""
    return _rewrite(lambda r: trace_id == r.get("trace_id")
                    and r.__setitem__("rerun", payload) is None)
