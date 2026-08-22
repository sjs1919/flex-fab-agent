# 错误处理规则（stack-python）

- 🚫 严禁「打日志然后丢弃」：异常必须向上传播（`raise ... from e` 或返回明确错误结构），上层无感知即缺陷。
- 错误信息用中文，专有名词保留英文。
- 工具返回值统一经 sandbox 三元组 `(result, success, retries)`；失败重试次数写日志并进 tracer span。
- 业务错误定义 sentinel 常量（如 `SCHEDULER_TIMEOUT`、`DB_UNAVAILABLE`），禁止裸字符串比较。
- 求解器超时不算失败：返回次优可行解 + 求解耗时（见蓝图 R-D1）。
