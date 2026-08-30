"""config.py 数据源扩展测试（M1 T1.0）。

覆盖：FLEX_FAB_AGENT_DATA_SOURCE 读取、get_mysql_dsn() 合成、缺口令报错。
"""
import importlib

import flex_fab_agent.config as cfg


def test_get_data_source_default_csv():
    assert cfg.get_data_source() == "csv"


def test_get_data_source_mysql(monkeypatch):
    monkeypatch.setenv("FLEX_FAB_AGENT_DATA_SOURCE", "mysql")
    assert cfg.get_data_source() == "mysql"


def test_get_mysql_dsn_has_creds(monkeypatch):
    monkeypatch.setattr(cfg, "_CREDENTIALS", {
        "MYSQL_HOST": "127.0.0.1", "MYSQL_PORT": "3306",
        "MYSQL_DB": "flex_fab_agent", "MYSQL_USER": "flex_fab_agent",
        "MYSQL_PASSWORD": "secret123",
    })
    dsn = cfg.get_mysql_dsn()
    assert dsn.startswith("mysql+pymysql://")
    assert "flex_fab_agent:secret123@127.0.0.1:3306/flex_fab_agent" in dsn


def test_get_mysql_dsn_missing_password(monkeypatch):
    monkeypatch.setattr(cfg, "_CREDENTIALS", {
        "MYSQL_HOST": "127.0.0.1", "MYSQL_PORT": "3306",
        "MYSQL_DB": "flex_fab_agent", "MYSQL_USER": "flex_fab_agent",
        "MYSQL_PASSWORD": "",
    })
    try:
        cfg.get_mysql_dsn()
        raise AssertionError("缺口令应抛 RuntimeError")
    except RuntimeError as e:
        assert "credentials.local.md" in str(e)


# ---- B3 模型路由（T4b.6）：get_routing_policy ----

def test_get_routing_policy_valid(monkeypatch):
    monkeypatch.setattr(cfg, "get_config", lambda c, k, d: '{"simple": "DeepSeek", "complex": "火山豆包(coding)"}')
    assert cfg.get_routing_policy() == {"simple": "DeepSeek", "complex": "火山豆包(coding)"}


def test_get_routing_policy_invalid_json(monkeypatch):
    monkeypatch.setattr(cfg, "get_config", lambda c, k, d: "{not json")
    assert cfg.get_routing_policy() == {}


def test_get_routing_policy_non_dict_json(monkeypatch):
    monkeypatch.setattr(cfg, "get_config", lambda c, k, d: '["a", "b"]')
    assert cfg.get_routing_policy() == {}


def test_get_routing_policy_empty_default(monkeypatch):
    """未配置 -> 回落默认 '{}'。"""
    monkeypatch.setattr(cfg, "get_config", lambda c, k, d: d)
    assert cfg.get_routing_policy() == {}


# ---- 自动排产调度器（定稿 v1 §5 config 行 / §6 config 单测） ----
# 模块级常量在 import 时读 env；env 覆盖用例用 importlib.reload 重新求值，
# finally 内 delenv + reload 恢复默认，避免污染后续用例。

def test_auto_approve_top_n_default_5():
    """AUTO_APPROVE_TOP_N 默认 5（定稿：20→5，FIFO 保留最近 N 版）。"""
    assert cfg.AUTO_APPROVE_TOP_N == 5


def test_auto_approve_top_n_env_override(monkeypatch):
    """AUTO_APPROVE_TOP_N env 可覆盖（int 解析）。"""
    monkeypatch.setenv("AUTO_APPROVE_TOP_N", "3")
    importlib.reload(cfg)
    try:
        assert cfg.AUTO_APPROVE_TOP_N == 3
    finally:
        monkeypatch.delenv("AUTO_APPROVE_TOP_N")
        importlib.reload(cfg)


def test_fifo_age_timeout_default_24():
    """FIFO_AGE_TIMEOUT 默认 24 模拟小时（最早待审版本超龄兜底阈值）。"""
    assert cfg.FIFO_AGE_TIMEOUT == 24


def test_fifo_age_timeout_env_override(monkeypatch):
    """FIFO_AGE_TIMEOUT env 可覆盖（float 解析）。"""
    monkeypatch.setenv("FIFO_AGE_TIMEOUT", "36")
    importlib.reload(cfg)
    try:
        assert cfg.FIFO_AGE_TIMEOUT == 36.0
    finally:
        monkeypatch.delenv("FIFO_AGE_TIMEOUT")
        importlib.reload(cfg)


def test_status_reserve_top_n_default_5():
    """STATUS_RESERVE_TOP_N 默认 5（自动推进器各状态留底数，2026-08-29 规格）。"""
    assert cfg.STATUS_RESERVE_TOP_N == 5


def test_status_reserve_top_n_env_override(monkeypatch):
    """STATUS_RESERVE_TOP_N env 可覆盖（int 解析）。"""
    monkeypatch.setenv("STATUS_RESERVE_TOP_N", "3")
    importlib.reload(cfg)
    try:
        assert cfg.STATUS_RESERVE_TOP_N == 3
    finally:
        monkeypatch.delenv("STATUS_RESERVE_TOP_N")
        importlib.reload(cfg)
