# 架构规则（stack-python / demo）

## 分层不变式

- 分层：`main.py/api.py`（入口）-> `agents/graph`（编排）-> `tools`（工具层）-> `core/rag/cache`（基座）-> `data`（数据）。禁止跨层反向依赖（如 tools 直接调 graph）。
- `auth/` 与 `observability/` 是横切层：经 registry/tracer 挂接，业务层不得绕过。

## 工具注册（唯一入口）

- 新工具**只经** `tools/registry.py:build_default_registry()` 注册，自动继承参数白名单/RBAC/sandbox 重试/tracer span 全管线；禁止散落的直调函数。
- 工具 =「函数 + docstring」：docstring 写清触发条件（LLM 选择依据），遵循现有风格。
- 写操作工具必须带 `read_only=False` 标记 + schema 注明权限要求（与 D3 治理衔接）。

## 数据源与配置

- `tools/data.py` 的 DataSource 抽象是数据层唯一入口（`DEMO_DATA_SOURCE=csv|mysql` 切换），工具函数签名返回 `list[dict]` 不变。
- `config.py` 是配置唯一来源；禁止业务代码散落 `os.getenv`。

## 求解器/模拟器边界

- `demo/scheduler/`、`demo/simulator/` 是独立模块，与 Agent 只经工具通信；模拟器不做业务决策，求解器无常驻进程。
