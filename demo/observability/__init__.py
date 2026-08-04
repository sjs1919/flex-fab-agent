"""观测层 -- 对应 Harness 第三层（可观测性）。

职责：把一次 Agent 运行的全过程结构化记录下来，供事后分析。
  - Span：一段带起止时间的工作单元（一次 LLM 调用 / 一次工具调用 / 一个图节点）
  - Tracer：收集 Span，汇总成 trace（含 token 用量、延迟、工具调用次数）
  - Exporter：把完成的 trace 导出外部 sink（console / OTel / OTLP）

为什么单独分层：
  week1-4 的可观测性散落在各处（call_llm 里 print、audit_logger 里 log），
  没有统一的 trace 视图。生产级 Harness 用 OpenTelemetry / Langfuse 自动埋点，
  这里提供同构的最小接口，导出 backend 可插拔（OTEL_EXPORTER）而不动业务代码。

当前实现：进程内内存收集 + 文本摘要 + 延迟批量导出（console/otel/otlp）。
剩余扩展点见 Tracer 类注释。
"""
from .exporter import (
    ConsoleExporter,
    NoneExporter,
    OTelSpanExporter,
    SpanExporter,
    build_exporter,
)
from .tracer import Span, Tracer, tracer

__all__ = [
    "Span",
    "Tracer",
    "tracer",
    "SpanExporter",
    "NoneExporter",
    "ConsoleExporter",
    "OTelSpanExporter",
    "build_exporter",
]
