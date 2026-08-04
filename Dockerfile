FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# CPU torch 先装（独立层缓存；sentence-transformers 依赖 torch，先装 CPU 版避免被拉 CUDA 版）
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu

WORKDIR /app

COPY requirements-demo.txt .
RUN pip install -r requirements-demo.txt

# demo/ 含业务数据（csv/contracts，随镜像）；运行时产物走挂载卷（DEMO_RUNTIME_DIR）
COPY demo/ ./demo/

ENV DEMO_RUNTIME_DIR=/data/runtime \
    OTEL_EXPORTER=console \
    CHECKPOINTER=sqlite \
    SEMANTIC_CACHE=on

EXPOSE 8000

CMD ["uvicorn", "demo.api:app", "--host", "0.0.0.0", "--port", "8000"]
