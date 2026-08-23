"""config.py 数据源扩展测试（M1 T1.0）。

覆盖：DEMO_DATA_SOURCE 读取、get_mysql_dsn() 合成、缺口令报错。
"""
import demo.config as cfg


def test_get_data_source_default_csv():
    assert cfg.get_data_source() == "csv"


def test_get_data_source_mysql(monkeypatch):
    monkeypatch.setenv("DEMO_DATA_SOURCE", "mysql")
    assert cfg.get_data_source() == "mysql"


def test_get_mysql_dsn_has_creds(monkeypatch):
    monkeypatch.setattr(cfg, "_CREDENTIALS", {
        "MYSQL_HOST": "127.0.0.1", "MYSQL_PORT": "3306",
        "MYSQL_DB": "demo_scheduling", "MYSQL_USER": "demo_sched",
        "MYSQL_PASSWORD": "secret123",
    })
    dsn = cfg.get_mysql_dsn()
    assert dsn.startswith("mysql+pymysql://")
    assert "demo_sched:secret123@127.0.0.1:3306/demo_scheduling" in dsn


def test_get_mysql_dsn_missing_password(monkeypatch):
    monkeypatch.setattr(cfg, "_CREDENTIALS", {
        "MYSQL_HOST": "127.0.0.1", "MYSQL_PORT": "3306",
        "MYSQL_DB": "demo_scheduling", "MYSQL_USER": "demo_sched",
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
