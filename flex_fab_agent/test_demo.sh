#!/usr/bin/env bash
# demo 一键自动化测试（Shell 入口）
#
# 用法：
#   bash test_demo.sh               # 全量单测
#   bash test_demo.sh --eval        # 单测 + 三层评估（真实 LLM）
#   bash test_demo.sh --report      # 单测 + 评估 + HTML 报告
#
set -e
cd "$(dirname "$0")"
python run_all_tests.py "$@"
