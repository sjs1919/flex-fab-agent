# 测试规则（stack-python）

- 测试先行（TDD）：先写失败测试，再写实现。
- 单测 mock LLM（零成本）；`run_all_tests.py` 是 CI 入口，全绿才过门禁。
- eval 回归基线 **>=7/10**（case >=0.6 判 pass）；ground_truth 与种子数据变更必须同步。
- 新工具必须有单测：正常路径 + 权限拒绝路径 + 参数白名单拒绝路径。
- 求解器测试带样例输入断言：C1-C9 约束自检 + 无可行解返回冲突清单（不静默）。
- 运行：`python run_all_tests.py`（全量）；`python -m pytest demo/path/test_x.py -v`（单个）。
