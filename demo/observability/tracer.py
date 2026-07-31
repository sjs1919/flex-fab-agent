"""轻量 Tracer -- 进程内 Span 收集器（OpenTelemetry 同构最小实现）。

设计要点：
  - tracer 是模块级单例，业务代码直接 from ..observability import tracer 使用，
    无需把 tracer 当参数层层传递（生产级用 contextvar 透传 trace_id）。
  - Span 用 contextmanager 管理（with tracer.span("llm") as s: ...），保证异常也结束。
  - 只采集最小信息（name/duration_ms/attributes），生产级会加 parent_span_id、
    链式采样、异步导出到 OTel collector / Langfuse。

生产扩展点（week5）：
  1. backend 替换：Tracer.export() 改为 OTel SpanExporter 或 Langfuse client
  2. 自动埋点：LangGraph 的 config.callbacks 注入，免去手动 with tracer.span(...)
  3. 采样：高 QPS 下按 trace_id 采样，避免全量上报
"""
import time
from contextlib import contextmanager
from dataclasses import dataclass, field


@dataclass
class Span:
    """一个工作单元的记录。生产级对应 OTel Span。"""
    name: str
    start_ms: float
    end_ms: float | None = None
    attributes: dict = field(default_factory=dict)

    @property
    def duration_ms(self) -> float | None:
        return None if self.end_ms is None else round(self.end_ms - self.start_ms, 1)


class Tracer:
    """进程内 trace 收集器。非线程安全（demo 单线程足够；生产用 contextvar 隔离）。"""

    def __init__(self) -> None:
        self._spans: list[Span] = []
        self._trace_start: float | None = None

    def reset(self) -> None:
        """每轮查询前清空，开始新一轮 trace。"""
        self._spans.clear()
        self._trace_start = None

    @contextmanager
    def span(self, name: str, **attributes):
        """记录一段工作单元。用法：with tracer.span("llm_call", model="doubao") as s: ..."""
        if self._trace_start is None:
            self._trace_start = time.perf_counter() * 1000
        s = Span(name=name, start_ms=time.perf_counter() * 1000, attributes=dict(attributes))
        self._spans.append(s)
        try:
            yield s
        finally:
            s.end_ms = time.perf_counter() * 1000

    def record(self, name: str, duration_ms: float, **attributes) -> None:
        """手动记录一个已完成的 span（不便用 contextmanager 时用）。"""
        if self._trace_start is None:
            self._trace_start = time.perf_counter() * 1000
        end = time.perf_counter() * 1000
        self._spans.append(Span(name, end - duration_ms, end, dict(attributes)))

    def get_summary(self) -> dict:
        """汇总本轮 trace：总耗时 + 各 span 明细 + 按类型分组的计数。"""
        total = 0.0
        if self._trace_start is not None and self._spans:
            last_end = max((s.end_ms for s in self._spans if s.end_ms), default=self._trace_start)
            total = round(last_end - self._trace_start, 1)
        by_kind: dict[str, int] = {}
        for s in self._spans:
            kind = s.name.split(":")[0]
            by_kind[kind] = by_kind.get(kind, 0) + 1
        return {
            "total_ms": total,
            "span_count": len(self._spans),
            "by_kind": by_kind,
            "spans": [
                {"name": s.name, "ms": s.duration_ms, "attrs": s.attributes}
                for s in self._spans
            ],
        }

    def format_text(self) -> str:
        """文本版 trace 摘要，供控制台打印。"""
        sm = self.get_summary()
        lines = [f"📊 Trace 摘要：总耗时 {sm['total_ms']}ms，{sm['span_count']} 个 span"]
        for kind, cnt in sm["by_kind"].items():
            lines.append(f"   {kind}: {cnt} 次")
        for sp in sm["spans"]:
            attrs = f" {sp['attrs']}" if sp["attrs"] else ""
            lines.append(f"   - {sp['name']}  {sp['ms']}ms{attrs}")
        return "\n".join(lines)


# 模块级单例：业务代码直接 import tracer 使用
tracer = Tracer()
