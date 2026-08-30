"""model.py CP-SAT 排程测试（M2 T2.4）。

覆盖：目标含加权迟到（交期权衡取更优）、C6 同机 interval 无重叠、
C3 机型匹配指派。小样例秒级（<5s）。
"""
from flex_fab_agent.scheduler import model, verify

BASE = "2026-09-01 00:00:00"


def _machines():
    return [
        {"id": "M0001", "process": "SLA", "model_type": "600", "cabin_size": 600, "max_weight": 100, "status": "空闲"},
        {"id": "M0005", "process": "MJS", "model_type": "450", "cabin_size": 450, "max_weight": 80, "status": "空闲"},
    ]


def _snapshot(machines=None, due={"ORD001": "2026-09-02", "ORD002": "2026-09-04"}):
    return {
        "orders": [
            {"id": "ORD001", "amount": 100000, "due_date": due["ORD001"], "penalty_rate": 0.01},
            {"id": "ORD002", "amount": 100000, "due_date": due["ORD002"], "penalty_rate": 0.01},
        ],
        "parts": [],
        "machines": machines or _machines(),
        "material": [
            {"process": "SLA", "rate_mm_h": 50, "post_process_hours": 1},
            {"process": "MJS", "rate_mm_h": 25, "post_process_hours": 3},
        ],
        "params": {"part_limit": 50, "weight_limit": 600, "emergency_reserve": 0.10,
                   "solver_max_time_seconds": 5},
    }


def _batch(pid, oid, process="SLA", model_type="600", edge=100):
    return {
        "id": pid, "order_ids": [oid], "process": process, "model_type": model_type,
        "machine_id": None, "start_time": None, "end_time": None, "post_process_end": None,
        "source": "整批",
        "parts": [{"part_id": pid, "order_id": oid, "material": process,
                   "length": edge, "width": 80, "height": 60, "weight": 2, "quantity": 1}],
    }


def test_model_machine_match():
    """C3：SLA 批只指派 SLA 机，MJS 批只指派 MJS 机。"""
    batches = [_batch("B1", "ORD001"), _batch("B2", "ORD002", process="MJS", model_type="450")]
    schedule, meta = model.solve_scheduling(batches, _snapshot())
    b1 = schedule["batches"][0]
    b2 = schedule["batches"][1]
    assert b1["machine_id"] == "M0001"  # SLA/600
    assert b2["machine_id"] == "M0005"  # MJS/450
    assert meta["status"] in ("OPTIMAL", "FEASIBLE")


def test_model_no_overlap():
    """C6：同机 interval（含静置）互斥，无重叠。"""
    batches = [_batch(f"B{i}", f"ORD00{i}") for i in range(1, 4)]
    s = _snapshot(due={f"ORD00{i}": "2026-09-05" for i in range(1, 4)})
    schedule, meta = model.solve_scheduling(batches, s)
    assert meta["status"] in ("OPTIMAL", "FEASIBLE")
    assert verify.verify(schedule, s) == []  # C1-C9 全过（含 C6）


def test_model_objective():
    """目标：加权迟到取更优解——宁可延期低权重订单，保护高权重订单按期。"""
    # BASE 固定为 09-01 当天：单机当天可用 21.6h，两批共 23h 排不下 → 必须延期其一
    machines = [{"id": "M0001", "process": "SLA", "model_type": "600",
                 "cabin_size": 600, "max_weight": 100, "status": "空闲"}]
    s = _snapshot(machines=machines,
                  due={"ORD001": "2026-09-01", "ORD002": "2026-09-01"})
    # ORD001：低权重 5000×0.003=15，批 13h（edge=600 → 12h+1h）
    # ORD002：高权重 800000×0.01=8000，批 10h（edge=450 → 9h+1h）
    s["orders"][0].update(amount=5000, penalty_rate=0.003)
    s["orders"][1].update(amount=800000, penalty_rate=0.01)
    batches = [_batch("B1", "ORD001", edge=600),
               _batch("B2", "ORD002", edge=450)]
    schedule, meta = model.solve_scheduling(batches, s, base_dt="2026-09-01 00:00:00")
    assert meta["status"] in ("OPTIMAL", "FEASIBLE")
    lat = meta["latencies"]  # {batch_id: 延期天数}
    assert lat["B1"] == 1 and lat["B2"] == 0, lat  # 延期低权重 ORD001，保护 ORD002
    assert meta["objective"] == 15  # 加权迟到 = 15（非 8000）


# ---- 定稿 v1 §5 model 行 / u-d-1：工艺组级部分成功 + 全不可行 ----

def test_model_group_partial_success():
    """u-d-1 部分成功：SLA 组可行 + SLM 组无工艺设备不可行 →
    只返回 SLA 组批次（SLM 组批次不入结果，保待排队下轮重排），
    meta 记 infeasible_groups / infeasible_order_ids（NFR-01 无解订单清单）。"""
    s = _snapshot(machines=_machines())  # SLA600 + MJS450，无 SLM 设备
    s["material"].append({"process": "SLM", "rate_mm_h": 15, "post_process_hours": 12})
    batches = [_batch("B1", "ORD001"),                                   # SLA/600 → M0001
               _batch("B2", "ORD002", process="SLM", model_type="600")]  # SLM 无设备 → INFEASIBLE
    schedule, meta = model.solve_scheduling(batches, s)
    assert [b["id"] for b in schedule["batches"]] == ["B1"]
    assert meta["infeasible_groups"] == ["SLM"]
    assert meta["infeasible_order_ids"] == ["ORD002"]
    assert meta["status"] == "OPTIMAL"  # 单组 OPTIMAL
    b1 = schedule["batches"][0]
    assert b1["machine_id"] == "M0001" and b1["start_time"]  # SLA 组正常求解赋值


def test_model_all_groups_infeasible():
    """全工艺组不可行 → 空排产表 + status=INFEASIBLE（persist 据此跳过建版本防刷屏）。"""
    s = _snapshot(machines=_machines())
    s["material"].append({"process": "SLM", "rate_mm_h": 15, "post_process_hours": 12})
    batches = [_batch("B1", "ORD001", process="SLM", model_type="600")]
    schedule, meta = model.solve_scheduling(batches, s)
    assert schedule["batches"] == []
    assert meta["status"] == "INFEASIBLE"
    assert meta["infeasible_groups"] == ["SLM"]
    assert meta["infeasible_order_ids"] == ["ORD001"]
