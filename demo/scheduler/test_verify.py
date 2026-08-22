"""verify.py C1-C9 程序化校验器测试（M2 T2.2，纯函数不连库）。

覆盖：合法排产表 0 违规；C1-C9 每类违规断言命中；超尺寸预警不静默。
"""
from demo.scheduler import verify


def _snapshot():
    return {
        "orders": [
            {"id": "ORD001", "amount": 100000, "due_date": "2026-09-10", "penalty_rate": 0.005},
            {"id": "ORD002", "amount": 50000, "due_date": "2026-09-12", "penalty_rate": 0.003},
        ],
        "parts": [
            {"id": "PART1", "order_id": "ORD001", "material": "SLA",
             "length": 100, "width": 80, "height": 60, "weight": 2, "quantity": 1},
            {"id": "PART_BIG", "order_id": "ORD001", "material": "SLA",
             "length": 650, "width": 200, "height": 150, "weight": 10, "quantity": 1},
        ],
        "machines": [
            {"id": "M0001", "process": "SLA", "model_type": "600", "cabin_size": 600, "max_weight": 100, "status": "空闲"},
            {"id": "M0002", "process": "MJS", "model_type": "450", "cabin_size": 450, "max_weight": 80, "status": "空闲"},
        ],
        "material": [
            {"process": "SLA", "rate_mm_h": 50, "post_process_hours": 1},
            {"process": "MJS", "rate_mm_h": 25, "post_process_hours": 3},
        ],
        "params": {"part_limit": 50, "weight_limit": 600, "emergency_reserve": 0.10,
                   "solver_max_time_seconds": 60},
    }


def _part(material="SLA", length=100, width=80, height=60, weight=2, quantity=1,
          order_id="ORD001", part_id="PART1"):
    return {"part_id": part_id, "order_id": order_id, "material": material,
            "length": length, "width": width, "height": height, "weight": weight, "quantity": quantity}


def _batch(**over):
    """合法 SLA 批次：M0001(600)，单 part 100×80×60，时长 2h 打印 + 1h 静置。"""
    batch = {
        "id": "B1",
        "order_ids": ["ORD001"],
        "parts": [_part()],
        "process": "SLA",
        "model_type": "600",
        "machine_id": "M0001",
        "start_time": "2026-09-01 08:00:00",
        "end_time": "2026-09-01 10:00:00",
        "post_process_end": "2026-09-01 11:00:00",
        "source": "整批",
    }
    batch.update(over)
    return batch


def _schedule(*batches):
    return {"batches": list(batches), "metrics": {}, "warnings": [], "conflicts": []}


def test_verify_all_pass():
    assert verify.verify(_schedule(_batch()), _snapshot()) == []


def test_verify_c1_same_material():
    """C1：同批混材料 → 违规。"""
    s = _schedule(_batch(parts=[_part(), _part(material="MJS", part_id="PART2")]))
    assert any("C1" in v for v in verify.verify(s, _snapshot()))


def test_verify_c2_overweight():
    """C2：Σ件重超承重 → 违规。"""
    s = _schedule(_batch(parts=[_part(weight=90), _part(weight=90, part_id="PART2")]))  # 180 > 100
    assert any("C2" in v for v in verify.verify(s, _snapshot()))


def test_verify_c2_cabin_edge():
    """C2：单边超舱（max 边 > cabin_size）→ 违规。"""
    s = _schedule(_batch(parts=[_part(length=650, width=200, height=150)]))  # 650 > 600
    assert any("C2" in v for v in verify.verify(s, _snapshot()))


def test_verify_c2_part_limit():
    """C2：件数超 part_limit（50）→ 违规。"""
    parts = [_part(part_id=f"P{i}", quantity=1) for i in range(55)]
    s = _schedule(_batch(parts=parts))
    assert any("C2" in v for v in verify.verify(s, _snapshot()))


def test_verify_c3_machine_match():
    """C3：机型不匹配（SLA batch → MJS 设备）→ 违规。"""
    s = _schedule(_batch(machine_id="M0002"))
    assert any("C3" in v for v in verify.verify(s, _snapshot()))


def test_verify_c4_duration():
    """C4：end-start ≠ max(单件时长) → 违规。"""
    s = _schedule(_batch(end_time="2026-09-01 09:00:00"))  # 1h ≠ 2h
    assert any("C4" in v for v in verify.verify(s, _snapshot()))


def test_verify_c5_source():
    """C5：source 非法值 → 违规。"""
    s = _schedule(_batch(source="未知"))
    assert any("C5" in v for v in verify.verify(s, _snapshot()))


def test_verify_c6_no_overlap():
    """C6：同设备两批时间重叠（含静置期）→ 违规。"""
    b1 = _batch()
    b2 = _batch(id="B2", parts=[_part(part_id="PART2")], order_ids=["ORD002"],
                start_time="2026-09-01 10:30:00", end_time="2026-09-01 12:30:00",
                post_process_end="2026-09-01 13:30:00")
    s = _schedule(b1, b2)  # b2 起点落在 b1 静置期 [10:00, 11:00)
    assert any("C6" in v for v in verify.verify(s, _snapshot()))


def test_verify_c7_due_date():
    """C7：batch 完成超批内最早交期 → 违规。"""
    s = _schedule(_batch(start_time="2026-09-11 06:00:00",
                         end_time="2026-09-11 08:00:00",
                         post_process_end="2026-09-11 09:00:00"))  # 完成 09-11 09:00 > due 09-10 23:59
    assert any("C7" in v for v in verify.verify(s, _snapshot(), strict_due=True))
    # 默认软约束：延期不算违规（延期入指标层延期清单）
    assert verify.verify(s, _snapshot()) == []


def test_verify_c8_daily_capacity():
    """C8：设备单日占用超 21.6h（10% 预留）→ 违规。"""
    # 8 批连续排满 09-01（每批 2h 打印 + 1h 静置 = 3h），总占用 24h > 21.6h
    batches = []
    for i in range(8):
        h = 3 * i
        end_h, post_h = h + 2, h + 3
        end_day = "2026-09-01" if end_h < 24 else "2026-09-02"
        post_day = "2026-09-01" if post_h < 24 else "2026-09-02"
        batches.append(_batch(
            id=f"B{i + 1}",
            parts=[_part(part_id=f"P{i + 1}")],
            start_time=f"2026-09-01 {h:02d}:00:00",
            end_time=f"{end_day} {end_h % 24:02d}:00:00",
            post_process_end=f"{post_day} {post_h % 24:02d}:00:00",
        ))
    s = _schedule(*batches)
    assert any("C8" in v for v in verify.verify(s, _snapshot()))


def test_verify_oversize_warning():
    """超尺寸 part（max>600）入预警清单，且排产表不含它（不静默）。"""
    s = _schedule(_batch())
    warnings = verify.oversize_warnings(_snapshot(), s)
    assert any(w["part_id"] == "PART_BIG" for w in warnings)
    in_schedule = {p["part_id"] for b in s["batches"] for p in b["parts"]}
    assert "PART_BIG" not in in_schedule
