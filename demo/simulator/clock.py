"""clock.py A 时钟层（M3 T3.1）-- sim_clock 单行表推进。

口径（v1 §5.2）：1 tick = 1 sim 小时；sim_clock 为单行表（id=1，
CHECK 约束保证）；本模块只做时间推进纯操作，心跳循环在 runner.py。
连接走 data 层连接池（conn 由调用方传入，事务归调用方管理）。
"""
from __future__ import annotations

from datetime import datetime

_TS_FMT = "%Y-%m-%d %H:%M:%S"


def init_clock(conn, start_time: datetime) -> None:
    """初始化/重置单行 sim_clock（幂等：无行插入，有行更新起点并停走）。"""
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM sim_clock")
        if cur.fetchone()[0]:
            cur.execute(
                "UPDATE sim_clock SET current_sim_time=%s, real_ratio=1, running=0 "
                "WHERE id=1",
                (start_time,),
            )
        else:
            cur.execute(
                "INSERT INTO sim_clock (id, current_sim_time, real_ratio, running) "
                "VALUES (1, %s, 1, 0)",
                (start_time,),
            )


def get_sim_time(conn) -> datetime:
    """读当前 sim 时间。未初始化时抛错（调用方须先 init_clock）。"""
    with conn.cursor() as cur:
        cur.execute("SELECT current_sim_time FROM sim_clock WHERE id=1")
        row = cur.fetchone()
    if not row:
        raise RuntimeError("sim_clock 未初始化，请先调用 init_clock()")
    return row[0] if isinstance(row[0], datetime) else datetime.strptime(str(row[0]), _TS_FMT)


def advance_sim_time(cur, hours: int = 1) -> None:
    """sim 时间 +hours（默认 1 tick = 1 小时）。接收 cursor 以便并入调用方事务。"""
    cur.execute(
        "UPDATE sim_clock SET current_sim_time = current_sim_time + INTERVAL %s HOUR "
        "WHERE id=1",
        (hours,),
    )
