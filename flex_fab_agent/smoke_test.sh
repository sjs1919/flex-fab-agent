#!/usr/bin/env bash
# demo 部署冒烟测试（Shell 入口）
#
# 用法：
#   bash smoke_test.sh                  # 全量冒烟（含 S10 调真实 LLM）
#   bash smoke_test.sh --skip-llm       # 跳过 LLM 调用（快速版）
#   bash smoke_test.sh --scan-secrets   # 只跑敏感信息扫描
#   bash smoke_test.sh --base-url http://localhost:8000   # HTTP 模式
#
set -e
cd "$(dirname "$0")"
python smoke_test.py "$@"
