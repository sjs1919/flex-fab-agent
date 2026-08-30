"""data.py MySQL 路径测试（M1 T2.2 分流 + T5.1 补全，需 WSL MySQL 可用）。

覆盖：_read_rows 参数化查询、特殊字符防注入、缺连接串 csv 兜底、R8 租户过滤。
"""
import logging

import flex_fab_agent.tools.data as data
from flex_fab_agent.tools import data as data_mod


def _mysql_query(query, params=()):
    """mysql 模式直连池执行，返回 list[dict]。"""
    conn = data_mod.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(query, params)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        conn.close()


def test_read_rows_mysql_param(monkeypatch):
    """mysql 分流：参数化查询返回 list[dict]，key=列名。"""
    monkeypatch.setenv("DEMO_DATA_SOURCE", "mysql")
    rows = data._read_rows("SELECT * FROM orders WHERE customer_id=%s", ("C001",))
    assert isinstance(rows, list) and rows
    assert {"id", "customer_id", "amount", "status"}.issubset(rows[0].keys())
    assert all(r["customer_id"] == "C001" for r in rows)


def test_read_rows_param_special_char(monkeypatch):
    """参数化查询：特殊字符不报错、不注入。"""
    monkeypatch.setenv("DEMO_DATA_SOURCE", "mysql")
    # 恶意参数：单引号拼接攻击，应被参数化隔离（查询结果为空而非注入全表）
    rows = data._read_rows("SELECT * FROM orders WHERE id=%s", ("ORD001' OR '1'='1",))
    assert rows == []


def test_read_rows_missing_dsn_fallback(monkeypatch, caplog):
    """缺连接串 → 报错提示 + 自动降级 csv 兜底，不抛异常。"""
    monkeypatch.setenv("DEMO_DATA_SOURCE", "mysql")
    monkeypatch.setattr(data_mod, "get_mysql_dsn", lambda: (_ for _ in ()).throw(
        RuntimeError("缺少 MySQL 口令")
    ))
    monkeypatch.setattr(data_mod, "_get_pool", lambda: (_ for _ in ()).throw(
        RuntimeError("缺少 MySQL 口令")
    ))
    with caplog.at_level(logging.WARNING, logger="flex_fab_agent.tools.data"):
        rows = data._read_rows("SELECT * FROM orders", filename="orders.csv")
    assert len(rows) >= 1  # csv 兜底结果
    assert any("兜底" in r.message for r in caplog.records)


def test_read_rows_csv_default(monkeypatch):
    """csv 分流：默认读 CSV。"""
    monkeypatch.setenv("DEMO_DATA_SOURCE", "csv")
    rows = data._read_rows("SELECT * FROM orders", filename="orders.csv")
    assert len(rows) == 15  # 现有 orders.csv 15 条


def test_read_rows_tenant_sql(monkeypatch):
    """R8：SQL 层租户过滤（mysql 路径）。"""
    monkeypatch.setenv("DEMO_DATA_SOURCE", "mysql")
    rows = data._read_rows("SELECT * FROM orders WHERE tenant_id=%s", ("nonexistent",))
    assert rows == []


# ---- T2.3 load_* 换体 ----

def test_load_orders_mysql_40(monkeypatch):
    """mysql 路径 load_orders 返回 seed 订单数（20，2026-08-28 从 40 调低），字段对齐新表。"""
    monkeypatch.setenv("DEMO_DATA_SOURCE", "mysql")
    orders = data.load_orders()
    assert len(orders) == 20
    assert {"id", "customer_id", "amount", "urgent", "priority", "due_date", "status"}.issubset(orders[0].keys())


def test_load_orders_tenant_nonexistent_mysql(monkeypatch):
    """R8：mysql 路径 load_orders(tenant_id=nonexistent) == []。"""
    monkeypatch.setenv("DEMO_DATA_SOURCE", "mysql")
    assert data.load_orders(tenant_id="nonexistent") == []


def test_load_machines_mysql_7(monkeypatch):
    """mysql 路径 load_machines 返回 7 台，字段含 process/model_type/cabin_size/max_weight。"""
    monkeypatch.setenv("DEMO_DATA_SOURCE", "mysql")
    machines = data.load_machines()
    assert len(machines) == 7
    assert {"process", "model_type", "cabin_size", "max_weight"}.issubset(machines[0].keys())


def test_load_parts_mysql(monkeypatch):
    """新增 load_parts：mysql 路径返回数百条（seed 20 订单 ~174 part），含包络盒三边/件重。"""
    monkeypatch.setenv("DEMO_DATA_SOURCE", "mysql")
    parts = data.load_parts()
    assert len(parts) >= 100
    assert {"id", "order_id", "material", "length", "width", "height", "weight"}.issubset(parts[0].keys())


def test_load_inventory_mysql_10(monkeypatch):
    """mysql 路径 load_inventory 返回 10 种材料。"""
    monkeypatch.setenv("DEMO_DATA_SOURCE", "mysql")
    items = data.load_inventory()
    assert len(items) == 10
    assert "库存量" in items[0]


def test_new_functions_passthrough(monkeypatch):
    """load_batches/load_config/load_preprocess_tasks 直读表（返回行数与库一致）。

    M2/M3 后 batches/preprocess_tasks 由求解器与 E2E 落库，不再假设空表。
    """
    monkeypatch.setenv("DEMO_DATA_SOURCE", "mysql")
    with data.get_connection() as conn:
        with conn.cursor() as cur:
            counts = {}
            for t in ("batches", "system_config", "preprocess_tasks"):
                cur.execute(f"SELECT COUNT(*) FROM {t}")
                counts[t] = cur.fetchone()[0]
    assert len(data.load_batches()) == counts["batches"]
    assert len(data.load_config()) == counts["system_config"]
    assert len(data.load_preprocess_tasks()) == counts["preprocess_tasks"]


# ---- T4.1 事务原子提交 ----

def test_transaction_atomic_rollback(monkeypatch):
    """同一事务写 2 行后制造异常 → 两行均不存在（无半写）。"""
    monkeypatch.setenv("DEMO_DATA_SOURCE", "mysql")
    try:
        with data.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO orders (id, customer_id, amount, urgent, priority, due_date, status, tenant_id) "
                    "VALUES ('TMP001','C001',1,0,0,'2026-09-30','待排队','default')"
                )
                cur.execute(
                    "INSERT INTO orders (id, customer_id, amount, urgent, priority, due_date, status, tenant_id) "
                    "VALUES ('TMP002','C001',2,0,0,'2026-09-30','待排队','default')"
                )
                raise RuntimeError("模拟失败：事务中途出错")
    except RuntimeError:
        pass
    rows = _mysql_query("SELECT id FROM orders WHERE id IN ('TMP001','TMP002')")
    assert rows == [], "失败路径出现半写"


def test_transaction_commit(monkeypatch):
    """成功路径：多写均落库。"""
    monkeypatch.setenv("DEMO_DATA_SOURCE", "mysql")
    with data.transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO orders (id, customer_id, amount, urgent, priority, due_date, status, tenant_id) "
                "VALUES ('TMP003','C001',3,0,0,'2026-09-30','待排队','default')"
            )
    rows = _mysql_query("SELECT id FROM orders WHERE id='TMP003'")
    assert rows, "成功路径数据未落库"
    # 清理测试数据
    with data.transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM orders WHERE id='TMP003'")
    assert _mysql_query("SELECT id FROM orders WHERE id='TMP003'") == []


# ---- M5a T5a.3 load_bad_parts ----

def _clear_test_bad_parts(all_rows: bool = False):
    """清理 bad_parts 测试数据（all_rows=True 全清：该表数据全部由测试/模拟器注入）。"""
    sql = "DELETE FROM bad_parts" if all_rows else "DELETE FROM bad_parts WHERE batch_id LIKE 'TESTBP%'"
    with data.transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)


def test_load_bad_parts_empty_table(monkeypatch):
    """空表返回 []（bad_parts 由 simulator 落库，测试清 TESTBP 前缀后验证）。"""
    monkeypatch.setenv("DEMO_DATA_SOURCE", "mysql")
    _clear_test_bad_parts(all_rows=True)
    assert data.load_bad_parts() == []


def test_load_bad_parts_filter_dimensions(monkeypatch):
    """插入后按 machine_id/batch_id/material 维度 filter_by 走通。"""
    monkeypatch.setenv("DEMO_DATA_SOURCE", "mysql")
    _clear_test_bad_parts()
    with data.transaction() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO bad_parts (batch_id, machine_id, material, part_count, sim_time, tenant_id) "
                "VALUES (%s,%s,%s,%s,%s,%s)",
                [("TESTBP01", "M00001", "SLA", 2, "2026-08-23 10:00:00", "default"),
                 ("TESTBP02", "M00002", "SLM", 1, "2026-08-23 11:00:00", "default")],
            )
    try:
        rows = data.load_bad_parts()
        mine = [r for r in rows if str(r["batch_id"]).startswith("TESTBP")]
        assert len(mine) == 2
        assert {"id", "batch_id", "machine_id", "material", "part_count", "sim_time",
                "tenant_id"}.issubset(mine[0].keys())
        by_machine = data.filter_by(rows, machine_id="M00001", batch_id="TESTBP01", material="SLA")
        assert len(by_machine) == 1 and by_machine[0]["part_count"] == 2
        by_material = data.filter_by(rows, material="SLM", batch_id="TESTBP02")
        assert len(by_material) == 1 and by_material[0]["machine_id"] == "M00002"
    finally:
        _clear_test_bad_parts()


def test_load_bad_parts_tenant_filter(monkeypatch):
    """R8：load_bad_parts(tenant_id=nonexistent) == []。"""
    monkeypatch.setenv("DEMO_DATA_SOURCE", "mysql")
    assert data.load_bad_parts(tenant_id="nonexistent") == []


# ---- 定稿 v1 §5/§6 T4.3：load_latest_batches 多活动版本聚合 ----

def test_load_latest_batches_aggregates_active_versions(monkeypatch):
    """弃 MAX(id)：聚合所有含未完成批次且版本非「已驳回」——插单后旧版本在途批次
    仍被资源页读出；驳回版本批次（被 E 门禁卡在前道）不入；全完成版本退出聚合。
    自建 AGG-* 批次自隔离，finally 清理不留共享库污染。"""
    monkeypatch.setenv("DEMO_DATA_SOURCE", "mysql")
    vids, bids = [], []
    try:
        with data.transaction() as conn:
            with conn.cursor() as cur:
                def ins_version(status):
                    cur.execute(
                        "INSERT INTO schedule_versions (created_at, triggered_by, params_json, "
                        "result_json, status) VALUES (NOW(), 'test', '{}', '{}', %s)", (status,))
                    vid = cur.lastrowid
                    vids.append(vid)
                    return vid

                def ins_batch(bid, vid, status, approval):
                    cur.execute(
                        "INSERT INTO batches (id, schedule_version_id, order_ids, parts_json, "
                        "process, model_type, status, approval_status, source) "
                        "VALUES (%s, %s, '[\"O1\"]', '[]', 'SLA', '600', %s, %s, '整批')",
                        (bid, vid, status, approval))
                    bids.append(bid)

                v1 = ins_version("待审核"); ins_batch("AGG-B1", v1, "打印中", "通过")  # 活动：在途
                v2 = ins_version("已驳回"); ins_batch("AGG-B2", v2, "前道", "通过")    # 驳回版本：不入
                v3 = ins_version("待审核"); ins_batch("AGG-B3", v3, "完成", "通过")    # 全完成：退出
        rows = data.load_latest_batches()
        mine = {r["id"] for r in rows if r["id"] in {"AGG-B1", "AGG-B2", "AGG-B3"}}
        assert "AGG-B1" in mine, "活动版本（打印中）在途批次应被聚合读出"
        assert "AGG-B2" not in mine, "驳回版本批次不入资源页"
        assert "AGG-B3" not in mine, "全完成版本批次退出聚合"
    finally:
        if bids or vids:
            with data.transaction() as conn:
                with conn.cursor() as cur:
                    if bids:
                        ph_b = ",".join(["%s"] * len(bids))
                        cur.execute(f"DELETE FROM batches WHERE id IN ({ph_b})", bids)
                    if vids:
                        ph_v = ",".join(["%s"] * len(vids))
                        cur.execute(f"DELETE FROM schedule_versions WHERE id IN ({ph_v})", vids)

