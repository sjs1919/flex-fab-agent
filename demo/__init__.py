"""demo -- week1-4 整合的多 Agent 排产助手（分层工程化版）。

分层结构（对应 Harness 编排-权限-观测三层）：
  core/        LLM 调用基座（主备 fallback）
  tools/       工具层（MCP 工具函数 + 注册表 + 数据层）
  rag/         合同知识库混合检索
  prompts/     各 Agent 系统提示词
  agents/      Agent 层（单 Agent / Supervisor / 子 Agent / 路由）
  graph/       LangGraph 编排
  auth/        鉴权（STS + RBAC + 审计）
  observability/ 观测层（week5 填充）

入口：python -m demo.main "你的问题"
"""
import sys

# Windows 控制台默认 GBK 编码，无法输出 emoji 状态符（♻️✅❌），
# 这里把标准输入/输出/错误重配为 UTF-8，用户无需手动设 PYTHONIOENCODING。
# stdin 也重配：--chat 多轮模式经 input() 读中文，GBK 解码会产 lone surrogate
# 致使打印时 utf-8 编码失败（surrogates not allowed）。
for _stream in (sys.stdin, sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
