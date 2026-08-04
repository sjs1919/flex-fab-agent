"""轻量 Tracer -- 进程内 Span 收集器 + 可插拔导出 backend（week5 #3 已落地）。

设计要点：
  - tracer 是模块级单例，业务代码直接 from ..observability import tracer 使用，
    无需把 tracer 当参数层层传递（生产级用 contextvar 透传 trace_id）。
  - Span 用 contextmanager 管理（with tracer.span("llm") as s: ...），保证异常也结束。
  - 采集 name/duration_ms/attributes + 绝对时间戳(start/end_wall_ns，供 OTel 导出)。
  - 导出延迟到整轮 query 结束（flush）：业务代码会在 with 退出后写 token 属性，
    立即导出会丢，故 in-memory Span 作事实源、flush 时批量导出。

导出 backend（OTEL_EXPORTER 环境变量，见 exporter.py）：
  - none    纯内存（等价 week4）
  - console 控制台结构化 JSON（默认，零基建）
  - otel    真 OpenTelemetry SDK，导到 ConsoleSpanExporter 或 OTLPSpanExporter(Jaeger)
  一轮 query 的所有 span 共享同一 trace_id，OTel 档下挂到同一个 OTel trace。

剩余扩展点：
  1. 自动埋点：LangGraph 的 config.callbacks 注入，免去手动 with tracer.span(...)
  2. 采样：高 QPS 下按 trace_id 采样，避免全量上报
  3. 异步导出 + 成本看板
"""
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field

from .exporter import build_exporter


@dataclass
class Span:
    """一个工作单元的记录。生产级对应 OTel Span。"""
    name: str
    start_ms: float
    end_ms: float | None = None
    attributes: dict = field(default_factory=dict)
    # 绝对 unix 纳秒，仅供 OTel 导出用；duration 仍用 perf_counter 的 start_ms/end_ms
    start_wall_ns: int | None = None
    end_wall_ns: int | None = None

    @property
    def duration_ms(self) -> float | None:
        return None if self.end_ms is None else round(self.end_ms - self.start_ms, 1)


class Tracer:
    """进程内 trace 收集器。非线程安全（demo 单线程足够；生产用 contextvar 隔离）。"""

    def __init__(self) -> None:
        self._spans: list[Span] = []
        self._trace_start: float | None = None
        self._trace_id: str = uuid.uuid4().hex[:16]
        self._exporter = build_exporter()

    @property
    def trace_id(self) -> str:
        """本轮 trace 的 id（导出时用于把所有 span 挂到同一个 OTel trace）。"""
        return self._trace_id

    def reset(self) -> None:
        """每轮查询前清空，开始新一轮 trace。"""
        self._spans.clear()
        self._trace_start = None
        self._trace_id = uuid.uuid4().hex[:16]

    @contextmanager
    def span(self, name: str, **attributes):
        """记录一段工作单元。用法：with tracer.span("llm_call", model="doubao") as s: ..."""
        if self._trace_start is None:
            self._trace_start = time.perf_counter() * 1000
        s = Span(
            name=name,
            start_ms=time.perf_counter() * 1000,
            attributes=dict(attributes),
            start_wall_ns=time.time_ns(),
        )
        self._spans.append(s)
        try:
            yield s
        finally:
            s.end_ms = time.perf_counter() * 1000
            s.end_wall_ns = time.time_ns()

    def record(self, name: str, duration_ms: float, **attributes) -> None:
        """手动记录一个已完成的 span（不便用 contextmanager 时用）。"""
        if self._trace_start is None:
            self._trace_start = time.perf_counter() * 1000
        end = time.perf_counter() * 1000
        end_ns = time.time_ns()
        self._spans.append(
            Span(
                name,
                end - duration_ms,
                end,
                dict(attributes),
                start_wall_ns=end_ns - int(duration_ms * 1_000_000),
                end_wall_ns=end_ns,
            )
        )

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

    def flush(self) -> None:
        """整轮 query 结束后导出本轮 trace（延迟批量导出，见 exporter.py）。"""
        self._exporter.export(self._trace_id, list(self._spans))


# 模块级单例：业务代码直接 import tracer 使用
tracer = Tracer()
