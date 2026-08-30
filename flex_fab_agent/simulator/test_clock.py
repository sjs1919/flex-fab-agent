"""clock.py A 时钟层测试（M3 T3.1，需 WSL MySQL）。

覆盖：init 幂等（单行 id=1）、advance 推进 +1h、get_sim_time 读取。
"""
from datetime import datetime

import pytest

from flex_fab_agent.simulator import clock
from flex_fab_agent.tools.data import get_connection

START = datetime(2026, 9, 1, 0, 0, 0)


@pytest.fixture(autouse=True)
def _clean_sim_clock():
    """每用例前清空 sim_clock，保证从已知状态开始。"""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM sim_clock")
        conn.commit()
    yield
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM sim_clock")
        conn.commit()


def test_clock_init_and_get():
    """init 后 sim_clock 单行 id=1，get_sim_time 返回起点。"""
    with get_connection() as conn:
        clock.init_clock(conn, START)
        conn.commit()
        t = clock.get_sim_time(conn)
    assert t == START


def test_clock_advance():
    """advance +1h：sim 时间推进 1 小时。"""
    with get_connection() as conn:
        clock.init_clock(conn, START)
        conn.commit()
        with conn.cursor() as cur:
            clock.advance_sim_time(cur, hours=1)
        conn.commit()
        t = clock.get_sim_time(conn)
    assert t == datetime(2026, 9, 1, 1, 0, 0)


def test_clock_init_idempotent_single_row():
    """init 两次幂等：仍单行，时间取最后一次起点。"""
    with get_connection() as conn:
        clock.init_clock(conn, START)
        clock.init_clock(conn, datetime(2026, 9, 2, 0, 0, 0))
        conn.commit()
        t = clock.get_sim_time(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM sim_clock")
            n = cur.fetchone()[0]
    assert n == 1
    assert t == datetime(2026, 9, 2, 0, 0, 0)
