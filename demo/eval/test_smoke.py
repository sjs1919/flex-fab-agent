"""pytest 冒烟测试：验证基础设施可用。"""
def test_smoke():
    assert True


def test_demo_package_importable():
    """demo 包能从 agent-training 根导入（验证 conftest 路径设置）。"""
    from demo.eval.metrics import compute_all_metrics
    assert compute_all_metrics is not None
