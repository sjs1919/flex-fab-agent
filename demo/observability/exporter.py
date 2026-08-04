"""Span 导出器 -- 把一轮 trace 完成的 span 序列化到外部 sink（观测层 #3）。

设计要点：
  - 导出是「延迟批量」：Tracer 在整轮 query 结束后调 exporter.export(trace_id, spans)，
    而非每个 span 结束就导出。原因是业务代码（llm_client.py）会在 with 块退出后
    继续往 span.attributes 写 token 用量，立即导出会丢这些属性。
  - backend 可插拔，由环境变量 OTEL_EXPORTER 选择：
      none    纯内存（等价 week4 行为）
      console 控制台结构化 JSON 行（默认，零基建，演示「导出」概念）
      otel    真 OpenTelemetry SDK：start_span + set_attribute + end，导到
              ConsoleSpanExporter（真 OTel JSON）或 OTLPSpanExporter（发本地 Jaeger）
  - OTel 档把一轮 query 的所有 span 挂到同一个 trace_id 下（Jaeger 里是一条完整链路，
    不是散落的单 span trace）。

为什么不直接用 OTel 的 start_as_current_span：
  那样 span 在 with 退出时立即 end 并导出，业务代码退出后写 token 属性的时机被错过。
  故这里保留 in-memory Span 作事实源，flush 时再转换成 OTel span 导出。
"""
from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from .tracer import Span


class SpanExporter(Protocol):
    """导出器协议：把一轮完成的 trace（一组 span）送到外部 sink。"""

    def export(self, trace_id: str, spans: list[Span]) -> None: ...


class NoneExporter:
    """空导出器：什么都不做（等价 week4 纯内存行为）。"""

    def export(self, trace_id: str, spans: list[Span]) -> None:
        pass


class ConsoleExporter:
    """控制台导出器：把每个 span 序列化成一行 JSON 打印。

    零基建依赖，演示「导出 = 把完成的 span 序列化到外部 sink」这一概念。
    与 Tracer.format_text() 的友好摘要互补：那是给人读的，这是给系统消费的结构化记录。
    """

    def export(self, trace_id: str, spans: list[Span]) -> None:
        print(f"\n📤 导出 trace {trace_id}（{len(spans)} span）-> console")
        for s in spans:
            record = {
                "trace_id": trace_id,
                "name": s.name,
                "ms": s.duration_ms,
                "attrs": s.attributes,
            }
            print("  " + json.dumps(record, ensure_ascii=False))


class OTelSpanExporter:
    """OpenTelemetry 导出器：用真 OTel SDK 把 span 导到 collector / Jaeger。

    sink 选择：
      - 设了 OTEL_EXPORTER_OTLP_ENDPOINT -> OTLPSpanExporter（gRPC，发往如本地 Jaeger 4317）
      - 否则 -> ConsoleSpanExporter（打印真 OTel JSON 格式）
    一轮 query 的所有 span 共享同一个 trace_id（经 NonRecordingSpan 根 context 链接），
    在 Jaeger 里呈现为一条完整多 span 链路。
    """

    def __init__(self) -> None:
        self._init()

    def _init(self) -> None:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

        endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
        if endpoint:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )
            sink = OTLPSpanExporter(endpoint=endpoint, insecure=True)
            self._sink_name = f"OTLP -> {endpoint}"
        else:
            sink = ConsoleSpanExporter()
            self._sink_name = "otel-console"

        self._otel = trace
        self._provider = TracerProvider(
            resource=Resource.create({"service.name": "demo-scheduling-agent"})
        )
        self._provider.add_span_processor(SimpleSpanProcessor(sink))
        self._tracer = self._provider.get_tracer("demo")

    def export(self, trace_id: str, spans: list[Span]) -> None:
        from opentelemetry.trace import (
            NonRecordingSpan,
            SpanContext,
            TraceFlags,
        )

        # 把 tracer 的 trace_id（16 hex）补齐成 OTel 128-bit（32 hex），造一个根 context，
        # 让本轮所有 span 挂到同一个 OTel trace 下。
        tid_hex = (trace_id + "0" * 32)[:32]
        sid_hex = (trace_id + "0" * 16)[:16]
        root_ctx = SpanContext(
            trace_id=int(tid_hex, 16),
            span_id=int(sid_hex, 16),
            is_remote=False,
            trace_flags=TraceFlags(TraceFlags.SAMPLED),
        )
        parent_ctx = self._otel.set_span_in_context(NonRecordingSpan(root_ctx))

        print(f"\n📤 导出 trace {trace_id}（{len(spans)} span）-> otel/{self._sink_name}")
        for s in spans:
            start_ns = s.start_wall_ns
            end_ns = s.end_wall_ns or s.start_wall_ns
            otel_span = self._tracer.start_span(
                s.name, context=parent_ctx, start_time=start_ns
            )
            for k, v in s.attributes.items():
                otel_span.set_attribute(k, v)
            otel_span.end(end_time=end_ns)
        self._provider.force_flush()


def build_exporter() -> SpanExporter:
    """按 OTEL_EXPORTER 环境变量构造导出器（默认 console）。"""
    mode = os.getenv("OTEL_EXPORTER", "console").lower()
    if mode == "none":
        return NoneExporter()
    if mode == "otel":
        try:
            return OTelSpanExporter()
        except ImportError as e:
            print(f"⚠️  OTEL_EXPORTER=otel 但 opentelemetry 未安装（{e}），降级 console")
            return ConsoleExporter()
    return ConsoleExporter()
