# 观测与审计规则（stack-python）

- 观测走 `observability/tracer.py` 的 span（contextmanager），禁止业务代码散落 `print`；调试输出用 tracer 或 logging。
- 新增子系统必须可被 trace_id 贯穿（LLM/工具/求解器/模拟器统一）。
- 鉴权决策、审批、重排触发、模拟器事件必须写 `auth/audit_logger.py`（JSONL，subject 标注来源）。
- 模拟器独立线程的 span 上下文必须与主线程隔离（线程局部），防止 span 串线。
- 求解器 span 必须记录：耗时、目标值、版本号、约束违反数。
