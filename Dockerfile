FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# pip 全局清华源（其余依赖用清华源加速）
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
# torch 必须走官方 CPU 索引：清华源/pypi 上的 torch 是 CUDA 版，会拉 2-3GB 无用 CUDA 依赖
# 构建时需传代理（build 命令见 docs/flex_fab_agent/部署指南）；或预置 HTTP_PROXY/HTTPS_PROXY build-arg
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu

WORKDIR /app

COPY requirements-flex-fab-agent.txt .
RUN pip install -r requirements-flex-fab-agent.txt

# flex_fab_agent/ 含业务数据（csv/contracts，随镜像）；运行时产物走挂载卷（FLEX_FAB_AGENT_RUNTIME_DIR）
COPY flex_fab_agent/ ./flex_fab_agent/
# 前端构建产物（web/ 本地 npm run build 产出，随镜像）→ FastAPI 同源托管
COPY web/dist ./web/dist

ENV FLEX_FAB_AGENT_RUNTIME_DIR=/data/runtime \
    OTEL_EXPORTER=console \
    CHECKPOINTER=sqlite \
    SEMANTIC_CACHE=on

EXPOSE 8000

CMD ["uvicorn", "flex_fab_agent.api:app", "--host", "0.0.0.0", "--port", "8000"]
