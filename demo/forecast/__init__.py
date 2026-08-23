"""forecast 包（M5a）：统计预测纯函数 + 聚合入口。

约束：forecast 不得 import assessment（assessment 延迟 import forecast 防循环依赖）。
"""
