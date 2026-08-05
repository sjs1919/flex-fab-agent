FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# pip 全局清华源（含 torch CPU 版），避免 PyPI 和 download.pytorch.org 国内卡顿
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
RUN pip install torch

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
