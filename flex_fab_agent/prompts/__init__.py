"""prompts 层 -- 各 Agent 的系统提示词。

分层组织：单 Agent / Supervisor / 审核 / 生产 / RAG 各自一个常量，
便于后续做 Prompt 版本管理与 A/B 测试（见差距表"Prompt 管理"项）。
"""
