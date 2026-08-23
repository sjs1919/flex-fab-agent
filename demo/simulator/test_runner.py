"""runner.py 线程/事务/隔离测试（M3 T3.6，需 WSL MySQL）。

覆盖：ticks 推进（时钟 +1h/tick + scene_version bump）、R-3 缓存失效、
D2 独立 tracer、tick 原子回滚。
"""
from datetime import datetime

import pytest

from demo.cache import llm_cache
from demo.observability.tracer import tracer as global_tracer
from demo.simulator import clock, engine, runner as runner_mod
from demo.tools.data import get_connection

T0 = datetime(2026, 9, 1, 8, 0, 0)


def _exec(sql, params=()):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
        conn.commit()


@pytest.fixture(autouse=True)
def _env():
    """清事件 + 固定时钟起点 + 保存/恢复 scene_version。"""
    _exec("DELETE FROM sim_events")
    with get_connection() as conn:
        clock.init_clock(conn, T0)
        conn.commit()
    saved = llm_cache._scene_version
    yield
    llm_cache._scene_version = saved
    _exec("DELETE FROM sim_events")


def test_runner_ticks():
    """SIM_TICK_SECONDS 加速跑 3 tick：sim_clock +3h，tick_count=3，scene_version +3。"""
    import time as _time
    start_version = llm_cache.get_scene_version()
    r = runner_mod.SimulatorRunner(tick_seconds=0.02)
    r.start()
    deadline = _time.monotonic() + 10
    try:
        while r.tick_count < 3:
            assert _time.monotonic() < deadline, "3 tick 未在 10s 内完成"
            assert r.is_alive(), "模拟器线程异常退出"
    finally:
        r.stop()
    with get_connection() as conn:
        t = clock.get_sim_time(conn)
    assert t == datetime(2026, 9, 1, 11, 0, 0)
    assert r.tick_count == 3
    assert llm_cache.get_scene_version() - start_version == 3


def test_scene_version_cache_invalidation(monkeypatch, tmp_path):
    """R-3：同 prompt 不同 scene_version -> get 不命中。"""
    monkeypatch.setattr(llm_cache, "_DB_PATH", tmp_path / "t.db")
    llm_cache._conn = None
    msgs = [{"role": "user", "content": "当前批次状态？"}]
    llm_cache.put(msgs, None, "m", 100, 0.3, content="旧答案",
                  tool_calls=None, prompt_tokens=1, completion_tokens=1)
    assert llm_cache.get(msgs, None, "m", 100, 0.3)["content"] == "旧答案"
    llm_cache.bump_scene_version()  # 模拟器 tick 推进
    assert llm_cache.get(msgs, None, "m", 100, 0.3) is None, "版本变更后必须失效"


def test_runner_uses_own_tracer():
    """D2：模拟器线程用独立 Tracer，全局 tracer 无 simulator:tick span。"""
    global_before = len(global_tracer._spans)
    r = runner_mod.SimulatorRunner()
    r.run_tick()
    global_after = len(global_tracer._spans)
    assert global_after == global_before, "模拟器不得污染全局 tracer"
    names = [s.name for s in r._tracer._spans]
    assert "simulator:tick" in names
    span = r._tracer._spans[-1]
    assert "sim_time" in span.attributes and "event_count" in span.attributes


def test_tick_atomic_rollback(monkeypatch):
    """tick 推进中异常 -> 整体回滚：时钟不推进、无半写。"""
    def _boom(conn, sim_time, params=None):
        raise RuntimeError("注入故障")
    monkeypatch.setattr(engine, "advance_tick", _boom)
    r = runner_mod.SimulatorRunner()
    with pytest.raises(RuntimeError):
        r.run_tick()
    with get_connection() as conn:
        t = clock.get_sim_time(conn)
    assert t == T0, "tick 失败时钟必须回滚（不 +1h）"
    assert r.tick_count == 0


def test_runner_circuit_breaker(monkeypatch):
    """连续失败熔断：tick 持续抛错达阈值 -> 心跳线程自动停止（不无限重试）。"""
    def _boom(conn, sim_time, params=None):
        raise RuntimeError("持续故障")
    monkeypatch.setattr(engine, "advance_tick", _boom)
    r = runner_mod.SimulatorRunner(tick_seconds=0.001)
    r.start()
    deadline = __import__("time").monotonic() + 15
    while r.is_alive() and __import__("time").monotonic() < deadline:
        pass
    assert not r.is_alive(), "连续失败后必须熔断停止"
    assert r.consecutive_failures >= runner_mod.MAX_CONSECUTIVE_FAILURES
    with get_connection() as conn:
        assert clock.get_sim_time(conn) == T0, "全部失败 tick 不得推进时钟"
