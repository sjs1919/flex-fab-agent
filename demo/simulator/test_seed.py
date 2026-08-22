"""seed.py 种子生成测试（M1 T1.3，需 WSL MySQL 可用）。

覆盖：reset 幂等、数量口径（7 设备/5 客户/30-50 订单/数百 part/10 库存）、
枚举合法、超尺寸样例（M2 预警验收预留）。
"""
from datetime import datetime

import demo.schema.migrate as mig
import demo.simulator.seed as seed_mod


def _query(sql, params=()):
    conn = seed_mod._connect()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    finally:
        conn.close()


def test_seed_reset_counts():
    """reset 后数量口径符合 todo T1.3 验收。"""
    seed_mod.reset()
    assert _query("SELECT COUNT(*) FROM customer")[0][0] == 5
    assert _query("SELECT COUNT(*) FROM machines")[0][0] == 7
    orders = _query("SELECT COUNT(*) FROM orders")[0][0]
    assert 30 <= orders <= 50
    parts = _query("SELECT COUNT(*) FROM parts")[0][0]
    assert parts >= 200
    assert _query("SELECT COUNT(*) FROM inventory")[0][0] == 10
    assert _query("SELECT COUNT(*) FROM material")[0][0] == 3


def test_seed_valid_enum_and_amount():
    """每订单 status 合法枚举、amount>0；part.material 合法。"""
    conn = seed_mod._connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT status, amount, urgent, priority, due_date FROM orders")
            for status, amount, urgent, priority, due_date in cur.fetchall():
                assert status in ("待排队", "已审核", "打印中", "完成")
                assert amount > 0
                assert urgent in (0, 1)
                assert priority >= 0
                assert due_date is not None
            cur.execute("SELECT material FROM parts")
            materials = {r[0] for r in cur.fetchall()}
            assert materials <= {"SLA", "MJS", "SLM"}
            assert materials  # 非空
    finally:
        conn.close()


def test_seed_oversize_sample():
    """至少 1 个 part 某边 >600mm（M2 超尺寸预警验收预留样例）。"""
    rows = _query("SELECT length, width, height FROM parts")
    assert any(max(r) > 600 for r in rows), "缺少超尺寸样例（某边>600）"


def test_seed_reset_idempotent():
    """reset 两次数据一致（幂等：先清后插）。"""
    seed_mod.reset()
    orders_a = _query("SELECT COUNT(*) FROM orders")[0][0]
    parts_a = _query("SELECT COUNT(*) FROM parts")[0][0]
    machines_a = _query("SELECT id FROM machines ORDER BY id")
    seed_mod.reset()
    assert _query("SELECT COUNT(*) FROM orders")[0][0] == orders_a
    assert _query("SELECT COUNT(*) FROM parts")[0][0] == parts_a
    assert _query("SELECT id FROM machines ORDER BY id") == machines_a


def test_seed_machines_spec():
    """设备构成符合 todo：SLA600×1+SLA450×2 / MJS600×1+MJS450×2 / SLM600×1。"""
    rows = _query("SELECT process, model_type, COUNT(*) FROM machines GROUP BY process, model_type ORDER BY process, model_type")
    spec = {(p, m): c for p, m, c in rows}
    assert spec[("SLA", "600")] == 1
    assert spec[("SLA", "450")] == 2
    assert spec[("MJS", "600")] == 1
    assert spec[("MJS", "450")] == 2
    assert spec[("SLM", "600")] == 1
