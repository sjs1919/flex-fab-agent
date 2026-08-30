"""data.py PooledDB 连接池测试（M1 T2.1，需 WSL MySQL 可用）。

覆盖：池取连接 SELECT 可用、并发取连接无异常、归还后无半开事务污染、
池为模块级单例（三并发入口共用）。
"""
import threading

from flex_fab_agent.tools import data


def test_pool_connection_select():
    conn = data.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            assert cur.fetchone()[0] == 1
    finally:
        conn.close()


def test_pool_concurrent():
    """N 线程同时取连接执行 SELECT 无异常。"""
    errors: list[Exception] = []
    barrier = threading.Barrier(8)

    def worker():
        try:
            barrier.wait()
            conn = data.get_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT COUNT(*) FROM orders")
                    cur.fetchone()
            finally:
                conn.close()
        except Exception as e:  # noqa: BLE001 - 收集到列表供断言
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not errors, f"并发取连接出现异常: {errors}"


def test_pool_no_half_open_txn():
    """归还连接无半开事务污染：INSERT 不 commit 归还，再取连接读不到脏数据。"""
    conn_a = data.get_connection()
    with conn_a.cursor() as cur:
        cur.execute(
            "INSERT INTO orders (id, customer_id, amount, urgent, priority, due_date, status, tenant_id) "
            "VALUES ('TMP001','C001',1,0,0,'2026-09-30','待排队','default')"
        )
    conn_a.close()  # 归还（reset 应 rollback 未提交事务）

    conn_b = data.get_connection()
    try:
        with conn_b.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM orders WHERE id='TMP001'")
            assert cur.fetchone()[0] == 0, "归还连接带出了未提交事务的脏数据"
    finally:
        conn_b.close()


def test_pool_singleton():
    """池为模块级单例：_get_pool 多次调用返回同一实例。"""
    assert data._get_pool() is data._get_pool()
