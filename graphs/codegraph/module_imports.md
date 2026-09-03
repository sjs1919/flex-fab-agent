# flex-fab-agent 模块依赖（由 codegraph 索引导出）

> 文件级 import 边聚合到顶层目录；src≠dst 才计。test 文件间的互导已忽略。

## 模块 import 流量（src -> dst）

| 源模块 | 目标模块 | import 边数 |
|--------|----------|------------|
| flex_fab_agent | tools | 21 |
| simulator | tools | 20 |
| flex_fab_agent | observability | 16 |
| tools | scheduler | 16 |
| scheduler | tools | 13 |
| scheduler | simulator | 10 |
| tools | flex_fab_agent | 9 |
| observability | tools | 8 |
| scheduler | flex_fab_agent | 8 |
| flex_fab_agent | auth | 8 |
| agents | graph | 7 |
| auth | flex_fab_agent | 7 |
| observability | flex_fab_agent | 6 |
| tools | core | 6 |
| agents | tools | 5 |
| graph | flex_fab_agent | 5 |
| flex_fab_agent | eval | 5 |
| simulator | cache | 5 |
| simulator | observability | 5 |
| simulator | scheduler | 5 |
| flex_fab_agent | simulator | 5 |
| tools | simulator | 5 |
| agents | prompts | 4 |
| flex_fab_agent | cache | 4 |
| cache | flex_fab_agent | 4 |
| eval | rag | 4 |
| scheduler | observability | 4 |
| tools | cache | 4 |
| agents | core | 3 |
| flex_fab_agent | agents | 3 |
| flex_fab_agent | core | 3 |
| flex_fab_agent | scheduler | 3 |
| core | flex_fab_agent | 3 |
| eval | observability | 3 |
| simulator | schema | 3 |
| agents | observability | 2 |
| agents | auth | 2 |
| auth | cache | 2 |
| auth | tools | 2 |
| core | observability | 2 |
| eval | core | 2 |
| forecast | tools | 2 |
| observability | cache | 2 |
| prompts | auth | 2 |
| rag | flex_fab_agent | 2 |
| rag | core | 2 |
| schema | tools | 2 |
| simulator | core | 2 |
| simulator | flex_fab_agent | 2 |
| flex_fab_agent | prompts | 2 |
| tools | forecast | 2 |
| agents | cache | 1 |
| auth | observability | 1 |
| cache | core | 1 |
| core | cache | 1 |
| eval | cache | 1 |
| eval | agents | 1 |
| forecast | flex_fab_agent | 1 |
| graph | core | 1 |
| graph | tools | 1 |
| guardrails | flex_fab_agent | 1 |
| observability | core | 1 |
| flex_fab_agent | backtest | 1 |
| scheduler | cache | 1 |
| web/src | flex_fab_agent | 1 |

## 依赖入度 Top（被 import 最多的模块）

- `tools`  被依赖 74 次
- `flex_fab_agent`  被依赖 49 次
- `observability`  被依赖 33 次
- `scheduler`  被依赖 24 次
- `core`  被依赖 21 次
- `cache`  被依赖 21 次
- `simulator`  被依赖 20 次
- `auth`  被依赖 12 次
- `graph`  被依赖 7 次
- `prompts`  被依赖 6 次
- `eval`  被依赖 5 次
- `rag`  被依赖 4 次
- `agents`  被依赖 4 次
- `schema`  被依赖 3 次
- `forecast`  被依赖 2 次
- `backtest`  被依赖 1 次

## 符号速查（文件 -> 符号）

- **flex_fab_agent/agents/production_agent.py** — 2 符号
  - function:_parse_json@14 ｜ function:assess_production_feasibility@24
- **flex_fab_agent/agents/review_agent.py** — 3 符号
  - function:_parse_json@18 ｜ function:build_review_context@29 ｜ function:review_order@55
- **flex_fab_agent/agents/router.py** — 5 符号
  - variable:RouteTarget@12 ｜ class:AgentRouter@15 ｜ method:__init__@18 ｜ method:classify@25 ｜ method:route@42
- **flex_fab_agent/agents/single_agent.py** — 9 符号
  - variable:logger@28 ｜ variable:_STATE_SENSITIVE_KEYWORDS@34 ｜ function:_is_state_sensitive@43 ｜ variable:_REJECTION_MARKERS@50 ｜ function:_looks_like_rejection@53 ｜ variable:_app@58
  - variable:_app_registry@59 ｜ function:_get_app@62 ｜ function:run_single_agent@71
- **flex_fab_agent/agents/supervisor.py** — 10 符号
  - class:SupervisorAgent@29 ｜ method:__init__@32 ｜ method:_setup_auth@39 ｜ method:dispatch_review@55 ｜ method:dispatch_production@71 ｜ method:_query_candidate_order_ids@84
  - method:orchestrate@103 ｜ method:_orchestrate@109 ｜ function:_recorded_execute@130 ｜ function:run_supervisor@188
- **flex_fab_agent/api.py** — 52 符号
  - variable:logger@38 ｜ variable:app@40 ｜ function:trace_id_middleware@53 ｜ function:http_exception_handler@82 ｜ function:global_exception_handler@98 ｜ variable:_registry@113
  - variable:_sim_runner@116 ｜ function:_get_sim_runner@119 ｜ function:_start_auto_scheduler@128 ｜ class:AskRequest@141 ｜ class:AskResponse@146 ｜ class:ScheduleApproveRequest@154
  - function:health@161 ｜ function:sim_start@178 ｜ function:sim_stop@208 ｜ function:sim_status@215 ｜ function:logs@236 ｜ function:schedule_latest@249
  - function:require_admin@274 ｜ function:schedule_load@293 ｜ class:ScheduleVersionList@299 ｜ class:ScheduleVersionsResponse@307 ｜ function:schedule_versions@312 ｜ function:schedule_approve@331
  - function:scheduler_status@341 ｜ function:order_tracking@349 ｜ function:kpi@359 ｜ variable:_RESOURCE_LOADERS@365 ｜ function:resources_list@377 ｜ class:PersonnelStatusRequest@390
  - function:set_personnel_status@395 ｜ function:dashboard_kpi_history@419 ｜ function:dashboard_costs@426 ｜ function:dashboard_traces@433 ｜ function:_persist_dashboard@439 ｜ function:_record_case@452
  - function:_run_agent_round@467 ｜ function:ask@494 ｜ function:debug_cases@509 ｜ function:debug_trace@521 ｜ function:_get_case@532 ｜ function:debug_rerun@543
  - function:debug_judge@559 ｜ function:debug_stats@574 ｜ function:debug_label@597 ｜ function:debug_admin_token@609 ｜ variable:_CONFIG_WHITELIST@624 ｜ function:get_config_view@632
  - function:put_config@648 ｜ function:thread_history@659 ｜ variable:_DIST@676 ｜ function:_spa@683
- **flex_fab_agent/auth/audit_logger.py** — 8 符号
  - variable:logger@20 ｜ function:_resolve_log_path@23 ｜ class:AuditLogger@31 ｜ method:__init__@38 ｜ method:trace_id@45 ｜ method:log@49
  - method:_persist@69 ｜ method:get_report@80
- **flex_fab_agent/auth/guard.py** — 2 符号
  - function:_force_tenant_enabled@22 ｜ function:check_tool_permission@27
- **flex_fab_agent/auth/mint.py** — 2 符号
  - variable:ROLES@15 ｜ function:main@18
- **flex_fab_agent/auth/quota.py** — 7 符号
  - variable:DEFAULT_LIMIT@14 ｜ variable:DEFAULT_WINDOW_SECONDS@15 ｜ class:WriteQuota@18 ｜ method:__init__@21 ｜ method:check_and_consume@26 ｜ method:reset@40
  - variable:write_quota@44
- **flex_fab_agent/auth/token_exchange.py** — 30 符号
  - variable:RoleType@21 ｜ variable:ROLE_PERMISSIONS@28 ｜ class:Token@46 ｜ method:is_expired@58 ｜ method:can_access@61 ｜ class:TokenStore@70
  - method:save@73 ｜ method:get@76 ｜ method:delete@79 ｜ method:delete_all@82 ｜ class:MemoryTokenStore@86 ｜ method:__init__@89
  - method:save@92 ｜ method:get@95 ｜ method:delete@98 ｜ method:delete_all@101 ｜ class:SqliteTokenStore@107 ｜ method:__init__@110
  - method:save@122 ｜ method:get@132 ｜ method:delete@149 ｜ method:delete_all@153 ｜ function:_build_token_store@160 ｜ class:STS@169
  - method:__init__@172 ｜ method:issue_user_token@175 ｜ method:exchange@189 ｜ method:get_token@217 ｜ method:revoke@220 ｜ method:revoke_all@224
- **flex_fab_agent/backtest/runner.py** — 5 符号
  - variable:BASELINE_COVERAGE@20 ｜ function:_run_case@23 ｜ function:run_backtest@50 ｜ function:print_summary@70 ｜ function:main@95
- **flex_fab_agent/backtest/scenarios.py** — 4 符号
  - function:load_scenarios@16 ｜ function:_handwritten_scenarios@29 ｜ function:_scenarios_from_cases@80 ｜ function:score_backtest@115
- **flex_fab_agent/cache/__init__.py** — 1 符号
  - variable:__all__@10
- **flex_fab_agent/cache/llm_cache.py** — 13 符号
  - variable:_DB_PATH@23 ｜ variable:_conn@24 ｜ variable:_scene_version@28 ｜ function:bump_scene_version@31 ｜ function:get_scene_version@38 ｜ function:_get_conn@43
  - function:is_enabled@62 ｜ function:_ttl@67 ｜ function:_cache_key@72 ｜ function:get@86 ｜ function:put@114 ｜ function:stats@131
  - function:clear@144
- **flex_fab_agent/cache/manager.py** — 12 符号
  - class:CacheManager@29 ｜ method:lookup_exact@40 ｜ method:store_exact@48 ｜ method:lookup_semantic@61 ｜ method:store_semantic@70 ｜ method:clear_state_entries@74
  - method:semantic_enabled@78 ｜ method:stats@84 ｜ method:clear@94 ｜ method:bump_scene_version@98 ｜ method:get_scene_version@102 ｜ variable:cache_manager@108
- **flex_fab_agent/cache/semantic_cache.py** — 12 符号
  - variable:logger@41 ｜ variable:_DB_DIR@43 ｜ variable:_COLLECTION_NAME@44 ｜ variable:_EMBEDDING_MODEL@45 ｜ variable:_collection@46 ｜ variable:_collection_lock@50
  - function:is_enabled@53 ｜ function:_ttl@57 ｜ function:_get_collection@71 ｜ function:get@90 ｜ function:put@120 ｜ function:clear_state_entries@142
- **flex_fab_agent/config.py** — 50 符号
  - variable:PROJECT_ROOT@15 ｜ variable:DATA_DIR@19 ｜ variable:RUNTIME_DIR@24 ｜ variable:CREDENTIALS_FILE@27 ｜ function:_parse_credentials_file@30 ｜ variable:_CREDENTIALS@77
  - function:_is_real_key@80 ｜ function:_cred@85 ｜ function:_env_or_cred@94 ｜ variable:PRIMARY_PROVIDER@115 ｜ variable:PROVIDERS@116 ｜ function:available_providers@150
  - variable:FLEX_FAB_AGENT_DATA_SOURCE@158 ｜ variable:LLM_CACHE@166 ｜ variable:LLM_CACHE_TTL@167 ｜ variable:SEMANTIC_CACHE@168 ｜ variable:CACHE_THRESHOLD@173 ｜ variable:SEMANTIC_CACHE_TTL@175
  - variable:SEMANTIC_CACHE_STATE_TTL@176 ｜ variable:LLM_BUDGET_LIMIT@179 ｜ variable:LLM_BUDGET_WARN@180 ｜ variable:CHECKPOINTER@183 ｜ variable:CONTEXT_MAX_CHARS@184 ｜ variable:CONTEXT_KEEP_RECENT@185
  - variable:CONTEXT_COMPRESS_CHUNK@186 ｜ variable:TOOL_TIMEOUT@189 ｜ variable:TOOL_MAX_RETRIES@190 ｜ variable:MCP_MODE@191 ｜ variable:GUARDRAILS_MODE@194 ｜ variable:FORCE_TENANT@195
  - variable:TOKEN_STORE@196 ｜ variable:WRITE_QUOTA_LIMIT@197 ｜ variable:WRITE_QUOTA_WINDOW@198 ｜ variable:AUDIT_LOG@199 ｜ variable:AUDIT_LOG_PATH@200 ｜ variable:SIM_TICK_SECONDS@203
  - variable:AUTO_SCHEDULE_ENABLED@206 ｜ variable:AUTO_SCHEDULE_TICK_INTERVAL@207 ｜ variable:AUTO_APPROVE_TOP_N@208 ｜ variable:FIFO_AGE_TIMEOUT@209 ｜ variable:STATUS_RESERVE_TOP_N@213 ｜ variable:OTEL_EXPORTER@216
  - variable:OTEL_EXPORTER_OTLP_ENDPOINT@217 ｜ function:get_data_source@220 ｜ function:get_mysql_dsn@225 ｜ function:get_redis_config@243 ｜ function:get_config@256 ｜ function:set_config@274
  - function:get_routing_policy@286 ｜ function:get_scene_version@297
- **flex_fab_agent/core/hf_utils.py** — 6 符号
  - variable:HF_MIRROR@18 ｜ function:_patch_hf_offline@21 ｜ function:_set_offline_env@36 ｜ function:_clear_offline_env@41 ｜ function:load_st_embedding@46 ｜ function:load_cross_encoder@82
- **flex_fab_agent/core/llm_client.py** — 15 符号
  - variable:_client_cache@29 ｜ variable:_LIMITS@31 ｜ variable:_TIMEOUT@32 ｜ class:_CachedFunction@38 ｜ class:_CachedToolCall@43 ｜ class:_CachedMessage@49
  - class:_CachedChoice@54 ｜ class:_CachedUsage@58 ｜ class:_CachedResponse@62 ｜ method:__init__@64 ｜ function:_build_client@80 ｜ function:_get_client@99
  - function:clear_client_cache@107 ｜ function:call_llm@114 ｜ function:call_llm_simple@222
- **flex_fab_agent/core/logging_setup.py** — 1 符号
  - function:setup_logging@16
- **flex_fab_agent/core/response.py** — 3 符号
  - function:_trace_id@19 ｜ function:ok@25 ｜ function:fail@35
- **flex_fab_agent/core/utils.py** — 10 符号
  - function:json_list@13 ｜ function:to_float@40 ｜ function:to_int@50 ｜ function:to_bool@60 ｜ function:fmt_dt@75 ｜ function:fmt_date@88
  - function:fmt_money@97 ｜ function:cap_limit@104 ｜ function:gen_id@111 ｜ variable:CUSTOMER_LEVEL_ORDER@124
- **flex_fab_agent/eval/__init__.py** — 1 符号
  - variable:__all__@8
- **flex_fab_agent/eval/judge.py** — 5 符号
  - variable:_CONTEXT_TOOLS@16 ｜ function:_extract_context@19 ｜ function:parse_judge_response@32 ｜ function:judge_semantic_quality@48 ｜ function:_judge_relevancy_only@110
- **flex_fab_agent/eval/judge_prompt.py** — 4 符号
  - variable:JUDGE_SYSTEM_PROMPT@10 ｜ function:build_judge_messages@25 ｜ variable:JUDGE_RELEVANCY_SYSTEM_PROMPT@42 ｜ function:build_relevancy_messages@55
- **flex_fab_agent/eval/metrics.py** — 3 符号
  - function:tool_call_accuracy@12 ｜ function:answer_completeness@32 ｜ function:compute_all_metrics@42
- **flex_fab_agent/eval/ragas_regression.py** — 12 符号
  - variable:BASELINE@24 ｜ variable:RAG_ANSWER_PROMPT@31 ｜ variable:GROUND_TRUTH@41 ｜ function:_llm_json@70 ｜ function:average_precision@88 ｜ function:faithfulness@103
  - function:answer_relevancy@127 ｜ function:context_precision@149 ｜ function:context_recall@167 ｜ function:_reviewer_perms@186 ｜ function:run_ragas_regression@192 ｜ function:main@242
- **flex_fab_agent/eval/report.py** — 5 符号
  - function:_fmt@9 ｜ function:_semantic_score@13 ｜ function:_score_bar@20 ｜ function:render_html_report@27 ｜ function:save_report@93
- **flex_fab_agent/eval/runner.py** — 6 符号
  - variable:GROUND_TRUTH_PATH@29 ｜ function:load_cases@32 ｜ function:_evaluate_single_case@41 ｜ function:run_eval@114 ｜ function:print_summary@150 ｜ function:main@222
- **flex_fab_agent/eval/trajectory.py** — 4 符号
  - function:path_efficiency@10 ｜ function:retry_quality@26 ｜ function:loop_detection_penalty@43 ｜ function:compute_trajectory_score@50
- **flex_fab_agent/eval/trajectory_capture.py** — 1 符号
  - function:rebuild_trajectory@15
- **flex_fab_agent/forecast/forecaster.py** — 7 符号
  - variable:DEFAULT_METHOD@17 ｜ variable:DEFAULT_WINDOW@18 ｜ variable:DEFAULT_ALPHA@19 ｜ function:_safe_int@22 ｜ function:_safe_float@29 ｜ function:history_daily@36
  - function:forecast@67
- **flex_fab_agent/forecast/models.py** — 2 符号
  - function:moving_average@9 ｜ function:exponential_smoothing@22
- **flex_fab_agent/graph/checkpointer.py** — 3 符号
  - variable:_BUILT@24 ｜ variable:_CHECKPOINTER@25 ｜ function:build_checkpointer@28
- **flex_fab_agent/graph/context_compressor.py** — 11 符号
  - variable:logger@16 ｜ variable:MAX_CHARS@18 ｜ variable:KEEP_RECENT@19 ｜ variable:COMPRESS_CHUNK_SIZE@20 ｜ function:estimate_chars@23 ｜ function:should_compress@28
  - function:_messages_to_text@33 ｜ function:build_compression_prompt@46 ｜ function:_sanitize_tool_messages@60 ｜ function:_truncate_large_messages@81 ｜ function:compress_messages@111
- **flex_fab_agent/graph/single_agent_graph.py** — 25 符号
  - variable:_COMPLEX_TOOLS@33 ｜ variable:_SCHEDULE_CONTEXT_TOOLS@38 ｜ variable:_QUERY_VERBS@46 ｜ variable:_DELAY_TOOLS@49 ｜ variable:_DELAY_MARKERS@52 ｜ variable:_DELAY_VERSION_RE@53
  - function:_extract_schedule_version@56 ｜ variable:_TOOL_MARKUP_MARKERS@73 ｜ variable:_FULLWIDTH_BAR@77 ｜ function:_looks_like_tool_markup@80 ｜ function:_sanitize_answer@84 ｜ class:ToolMarkupOutput@91
  - variable:_NUDGE@98 ｜ variable:_SUMMARY_NUDGE@102 ｜ variable:_GRACEFUL_FALLBACK@105 ｜ variable:LOOP_GUARD_FALLBACK_PREFIX@109 ｜ variable:SUMMARY_FALLBACK_PREFIX@112 ｜ function:call_llm_agentic@115
  - function:_extract_delay_context@129 ｜ function:build_single_agent_graph@154 ｜ function:analyze_intent@159 ｜ function:select_and_execute@165 ｜ function:evaluate_results@280 ｜ function:should_continue@474
  - function:generate_answer@503
- **flex_fab_agent/graph/state.py** — 1 符号
  - class:AgentState@12
- **flex_fab_agent/guardrails/__init__.py** — 2 符号
  - class:GuardrailsResult@17 ｜ function:run_guardrails@25
- **flex_fab_agent/guardrails/content_filter.py** — 3 符号
  - class:GuardrailsViolation@12 ｜ method:__init__@14 ｜ function:filter_output@20
- **flex_fab_agent/guardrails/rules.py** — 6 符号
  - variable:BLOCKED_PATTERNS@10 ｜ variable:SENSITIVE_PATTERNS@20 ｜ variable:REQUIRED_SECTIONS_FOR_SCHEDULING@26 ｜ function:check_blocked_content@31 ｜ function:check_missing_sections@40 ｜ function:check_sensitive_info@48
- **flex_fab_agent/main.py** — 7 符号
  - variable:FLEX_FAB_AGENT_SCENARIOS@26 ｜ function:selfcheck@35 ｜ function:main@58 ｜ function:_run_sim@138 ｜ function:_rollback_prompt@174 ｜ function:_run_with_trace@186
  - function:_chat@201
- **flex_fab_agent/observability/__init__.py** — 1 符号
  - variable:__all__@27
- **flex_fab_agent/observability/case_collector.py** — 13 符号
  - variable:CASES_PATH@22 ｜ variable:CHITCHAT_WORDS@25 ｜ variable:_WRITE_LOCK@32 ｜ variable:_STRIP_CHARS@35 ｜ function:classify@38 ｜ function:_collection_enabled@47
  - function:_sample_rate@52 ｜ function:record_case@60 ｜ function:load_cases@82 ｜ function:_rewrite@107 ｜ function:label_case@119 ｜ function:attach_judge@126
  - function:attach_rerun@132
- **flex_fab_agent/observability/cost.py** — 20 符号
  - variable:PRICE_PER_MILLION@29 ｜ variable:DEFAULT_PRICE@35 ｜ variable:BUDGET_LIMIT@38 ｜ variable:BUDGET_WARN@40 ｜ class:CostEntry@44 ｜ method:total_tokens@56
  - class:BudgetExceededError@60 ｜ method:__init__@62 ｜ class:CostTracker@71 ｜ method:__init__@74 ｜ method:record@79 ｜ method:total_cost@113
  - method:total_tokens@118 ｜ method:is_budget_exceeded@123 ｜ method:by_provider@126 ｜ method:by_model@141 ｜ method:get_summary@155 ｜ method:format_text@166
  - method:reset@180 ｜ variable:cost_tracker@188
- **flex_fab_agent/observability/dashboard.py** — 10 符号
  - function:record_kpi_snapshot@23 ｜ function:record_cost@35 ｜ function:record_trace@54 ｜ function:kpi_history@74 ｜ function:cost_by_model@91 ｜ function:trace_summary@124
  - function:get_trace@142 ｜ function:_svg_line@166 ｜ function:render_static_html@181 ｜ function:main@228
- **flex_fab_agent/observability/exporter.py** — 11 符号
  - class:SpanExporter@30 ｜ method:export@33 ｜ class:NoneExporter@36 ｜ method:export@39 ｜ class:ConsoleExporter@43 ｜ method:export@50
  - class:OTelSpanExporter@62 ｜ method:__init__@72 ｜ method:_init@75 ｜ method:export@99 ｜ function:build_exporter@131
- **flex_fab_agent/observability/operation_log.py** — 8 符号
  - variable:logger@19 ｜ variable:_HTTP_DEBUG_PREFIX@23 ｜ variable:_HTTP_MANUAL_PREFIXES@24 ｜ variable:_EXCLUDE_PREFIXES@27 ｜ variable:_ACTION_PREFIXES@30 ｜ function:classify_request@52
  - function:record_operation@76 ｜ function:query_operations@100
- **flex_fab_agent/observability/request_context.py** — 5 符号
  - variable:_request_trace_id@28 ｜ function:get_trace_id@33 ｜ function:set_trace_id@42 ｜ function:new_trace_id@47 ｜ function:reset_trace_id@54
- **flex_fab_agent/observability/tracer.py** — 12 符号
  - class:Span@27 ｜ method:duration_ms@40 ｜ class:Tracer@44 ｜ method:__init__@52 ｜ method:trace_id@59 ｜ method:reset@63
  - method:span@75 ｜ method:record@96 ｜ method:get_summary@113 ｜ method:format_text@134 ｜ method:flush@145 ｜ variable:tracer@151
- **flex_fab_agent/prompts/system_prompts.py** — 4 符号
  - variable:SINGLE_AGENT_PROMPT@10 ｜ variable:REVIEW_AGENT_PROMPT@55 ｜ variable:PRODUCTION_AGENT_PROMPT@96 ｜ variable:SUPERVISOR_PROMPT@118
- **flex_fab_agent/prompts/versioning.py** — 5 符号
  - variable:_VERSIONS_DIR@15 ｜ function:_read_meta@18 ｜ function:load_system_prompt@22 ｜ function:rollback@34 ｜ function:list_versions@52
- **flex_fab_agent/rag/knowledge_base.py** — 14 符号
  - variable:logger@20 ｜ variable:DB_DIR@22 ｜ variable:CONTRACTS_DIR@23 ｜ variable:DELAY_RECORD@24 ｜ variable:COLLECTION_NAME@25 ｜ variable:EMBEDDING_MODEL@26
  - variable:DOC_PERMISSION@30 ｜ function:doc_permission@33 ｜ variable:_embedding_function@38 ｜ function:_get_ef@41 ｜ function:load_documents@49 ｜ function:chunk_text@59
  - function:get_or_build_vectorstore@74 ｜ function:retrieve@101
- **flex_fab_agent/rag/retriever.py** — 15 符号
  - variable:logger@20 ｜ variable:RERANKER_MODEL@22 ｜ variable:_PROXY@24 ｜ variable:CONFIDENTIAL_ROLES@27 ｜ variable:_rag_state@29 ｜ function:load_reranker@32
  - function:build_bm25_index@40 ｜ function:bm25_search@51 ｜ function:rrf_fuse@65 ｜ function:rerank@85 ｜ function:_role_from_token@100 ｜ function:_allowed_sources@113
  - function:retrieve_hybrid@118 ｜ function:_ensure_rag@135 ｜ function:search_knowledge_base@146
- **flex_fab_agent/run_all_tests.py** — 6 符号
  - variable:FLEX_FAB_AGENT_ROOT@19 ｜ variable:PYTHON@20 ｜ function:run_unit_tests@23 ｜ function:run_eval@32 ｜ function:generate_report@44 ｜ function:main@57
- **flex_fab_agent/run_eval_report.py** — 2 符号
  - variable:AGENT_TRAINING_ROOT@8 ｜ function:main@17
- **flex_fab_agent/scheduler/assessment.py** — 31 符号
  - variable:DEFAULT_T_WINDOW_H@19 ｜ variable:DEFAULT_WORKERS@20 ｜ variable:DEFAULT_SHIFTS@21 ｜ variable:DEFAULT_SHIFT_HOURS@22 ｜ variable:DEFAULT_CHANGEOVER_MIN@23 ｜ variable:DEFAULT_PART_EFF@24
  - variable:DEFAULT_PLAN_REVIEW_HOURS@25 ｜ variable:DAILY_UTILIZATION@27 ｜ function:_cfg@30 ｜ function:_f@37 ｜ function:_i@44 ｜ function:_to_due_datetime@51
  - function:zone_color@68 ｜ function:t_window_availability@80 ｜ function:missing_machines@107 ｜ function:part_machine_hours@114 ｜ function:preprocess_net_capacity_h@119 ｜ function:preprocess_task_hours@129
  - function:clear_eta_hours@145 ｜ function:compute_ctp@156 ｜ function:_now@185 ｜ function:_rates@199 ｜ function:_latest_batches@207 ｜ function:_completed_batches@229
  - function:_preprocess_params@246 ｜ function:_per_part_eff@257 ｜ function:preprocess_load@265 ｜ function:_demand_machine_hours@303 ｜ function:load_assessment@320 ｜ function:_forecast_reserved_days@432
  - function:compute_ctp_from_db@458
- **flex_fab_agent/scheduler/auto_scheduler.py** — 15 符号
  - variable:logger@22 ｜ class:AutoScheduler@25 ｜ method:__init__@26 ｜ method:start@45 ｜ method:stop@54 ｜ method:_loop@62
  - method:_read_sim_time@79 ｜ method:run_once@92 ｜ method:_run_locked@98 ｜ method:_auto_schedule@111 ｜ method:_fifo_approve@153 ｜ method:request_rerun@217
  - method:status@223 ｜ variable:_scheduler_instance@237 ｜ function:get_scheduler@240
- **flex_fab_agent/scheduler/model.py** — 19 符号
  - variable:OVERSIZE_THRESHOLD@21 ｜ variable:_TS_FMT@22 ｜ variable:_DAY_SEC@23 ｜ function:_proj@26 ｜ function:_to_part@32 ｜ function:pack_parts@41
  - function:_fits@64 ｜ function:_sort_key@79 ｜ function:_material_map@183 ｜ function:_batch_duration_sec@192 ｜ function:_default_base_dt@200 ｜ function:_due_sec@207
  - function:_batch_weight@214 ｜ function:solve_scheduling@223 ｜ function:_daily_overlap@292 ｜ function:_greedy_hint@305 ｜ function:_solve_group@353 ｜ function:_out_batch@572
  - function:_infeasible_schedule@586
- **flex_fab_agent/scheduler/snapshot.py** — 9 符号
  - variable:DEFAULT_PARAMS@19 ｜ variable:_NUMERIC@25 ｜ function:_fetch@29 ｜ function:_to_float@35 ｜ function:_date_str@39 ｜ function:_normalize_machines@46
  - function:load_snapshot@63 ｜ function:get_solver_params@131 ｜ function:main@146
- **flex_fab_agent/scheduler/solver.py** — 9 符号
  - variable:_TS_FMT@23 ｜ class:PersistConcurrentLockError@26 ｜ function:_dt@30 ｜ function:_due_dt@34 ｜ function:_delay_days@40 ｜ function:compute_metrics@44
  - function:persist@107 ｜ function:solve@193 ｜ function:main@256
- **flex_fab_agent/scheduler/verify.py** — 9 符号
  - variable:_TS_FMT@18 ｜ variable:OVERSIZE_THRESHOLD@19 ｜ function:_dt@22 ｜ function:_due_dt@26 ｜ function:_hours@32 ｜ function:_daily_occupation@36
  - function:verify@51 ｜ function:oversize_warnings@144 ｜ function:main@163
- **flex_fab_agent/schema/migrate.py** — 22 符号
  - variable:SCHEMA_SQL@21 ｜ variable:CURRENT_VERSION@22 ｜ variable:_BAD_PARTS_DDL@25 ｜ variable:_DASHBOARD_DDL@44 ｜ variable:_PERSONNEL_DDL@86 ｜ variable:_OPERATION_LOG_DDL@98
  - function:_column_exists@118 ｜ function:_up_v2@127 ｜ function:_down_v2@136 ｜ function:_up_v3@143 ｜ function:_down_v3@148 ｜ function:_up_v4@154
  - function:_down_v4@159 ｜ function:_up_v5@164 ｜ function:_down_v5@169 ｜ variable:_MIGRATIONS@174 ｜ function:_connect@177 ｜ function:_table_names@182
  - function:up@187 ｜ function:down@220 ｜ function:status@246 ｜ function:main@261
- **flex_fab_agent/simulator/clock.py** — 4 符号
  - variable:_TS_FMT@11 ｜ function:init_clock@14 ｜ function:get_sim_time@32 ｜ function:advance_sim_time@42
- **flex_fab_agent/simulator/constants.py** — 4 符号
  - variable:LEVEL_SCORE@7 ｜ variable:PART_DIM_RANGE@10 ｜ variable:PART_WEIGHT_RANGE@17 ｜ function:calc_priority@24
- **flex_fab_agent/simulator/engine.py** — 17 符号
  - variable:SHIFT_FACTOR@24 ｜ function:effective_man_hours@27 ｜ function:advance_batches@32 ｜ function:_orders_done_this_tick@99 ｜ function:_scrap_inspect@135 ｜ function:advance_preprocess@170
  - function:mark_overdue_orders@188 ｜ function:advance_tick@211 ｜ function:fire_events@227 ｜ function:check_hard_infeasibility@245 ｜ function:_fire_machine_failure@280 ｜ function:_fire_repair_done@317
  - function:_fire_new_order@329 ｜ function:_fire_order_change@336 ｜ function:_fire_leave@357 ｜ function:_fire_restock@383 ｜ variable:_HANDLERS@399
- **flex_fab_agent/simulator/events.py** — 7 符号
  - variable:PARAMS_DEFAULT@27 ｜ function:get_sim_params@43 ｜ function:_next_interval_hours@58 ｜ function:schedule_next@74 ｜ function:_next_seq@87 ｜ function:generate_new_order@95
  - function:seed_schedule_events@139
- **flex_fab_agent/simulator/runner.py** — 11 符号
  - variable:logger@26 ｜ variable:MAX_CONSECUTIVE_FAILURES@30 ｜ class:SimulatorRunner@33 ｜ method:__init__@36 ｜ method:run_tick@46 ｜ method:_need_reschedule@91
  - method:_record_kpi_snapshot@108 ｜ method:start@120 ｜ method:_loop@129 ｜ method:stop@152 ｜ method:is_alive@159
- **flex_fab_agent/simulator/seed.py** — 20 符号
  - variable:SEED_TABLES@32 ｜ variable:CUSTOMERS@35 ｜ variable:MACHINES@45 ｜ variable:MATERIAL@56 ｜ variable:SYSTEM_CONFIG_ROWS@60 ｜ variable:INVENTORY@81
  - variable:ORDER_COUNT@96 ｜ function:_connect@99 ｜ function:_clear@104 ｜ function:_seed_customers@125 ｜ function:_seed_machines@133 ｜ function:_seed_material@141
  - function:_seed_inventory@147 ｜ function:seed_personnel@156 ｜ function:_seed_system_config@171 ｜ function:_seed_orders@180 ｜ function:_seed_parts@204 ｜ function:seed@229
  - function:reset@256 ｜ function:main@269
- **flex_fab_agent/simulator/states.py** — 11 符号
  - variable:BATCH_TRANSITIONS@12 ｜ variable:MACHINE_TRANSITIONS@20 ｜ variable:ORDER_TRANSITIONS@33 ｜ variable:ORDER_NOOP_TRANSITIONS@42 ｜ variable:_TRANSITIONS@44 ｜ function:assert_transition@48
  - function:log_state_change@57 ｜ function:set_batch_status@72 ｜ function:set_machine_status@84 ｜ function:set_order_status@96 ｜ function:set_machine_batch@116
- **flex_fab_agent/smoke_test.py** — 25 符号
  - variable:AGENT_TRAINING_ROOT@41 ｜ variable:results@49 ｜ variable:fail_count@50 ｜ variable:_skip_llm_mode@51 ｜ function:_pass@54 ｜ function:_fail@59
  - function:_skip@66 ｜ function:_section@71 ｜ function:s0_secrets_scan@81 ｜ function:s1_foundation@164 ｜ function:s2_data_layer@204 ｜ function:s3_data_integrity@234
  - variable:_http_client@272 ｜ function:_get_http_client@275 ｜ function:s4_api_health@287 ｜ function:s5_api_kpi@315 ｜ function:s6_api_config@328 ｜ function:_call_api@344
  - function:s7_scheduling@367 ｜ function:s8_api_schedule@391 ｜ function:s9_simulator@413 ｜ function:s10_agent_ask@459 ｜ function:s11_frontend@504 ｜ function:main@529
  - function:_print_summary@605
- **flex_fab_agent/tools/data.py** — 27 符号
  - variable:logger@27 ｜ variable:_pool@32 ｜ function:_get_pool@35 ｜ function:get_connection@56 ｜ function:create_raw_connection@61 ｜ function:transaction@85
  - function:_read_rows@104 ｜ function:_read_csv@127 ｜ function:_with_tenant@136 ｜ function:_row_filter@145 ｜ variable:_ORDERS_CSV_ALIAS@155 ｜ variable:_ORDERS_CSV_STATUS@156
  - function:normalize_order_status@170 ｜ function:_normalize_orders_row@179 ｜ function:load_orders@190 ｜ function:load_inventory@197 ｜ function:load_machines@203 ｜ function:load_customers@209
  - function:load_parts@215 ｜ function:load_batches@221 ｜ function:load_latest_batches@230 ｜ function:load_personnel@248 ｜ function:load_config@253 ｜ function:load_preprocess_tasks@261
  - function:load_bad_parts@269 ｜ function:format_table@275 ｜ function:filter_by@291
- **flex_fab_agent/tools/mcp_client.py** — 9 符号
  - class:MCPToolClient@23 ｜ method:__init__@26 ｜ method:_ensure_running@33 ｜ method:_send_json_rpc@54 ｜ method:call_tool@75 ｜ method:list_tools@87
  - method:close@92 ｜ variable:_clients@100 ｜ function:get_mcp_client@103
- **flex_fab_agent/tools/mcp_servers.py** — 2 符号
  - function:build_order_server@19 ｜ function:build_resource_server@28
- **flex_fab_agent/tools/order_tools.py** — 5 符号
  - function:_orders_table@20 ｜ function:_enrich@25 ｜ function:query_orders@49 ｜ function:get_order_detail@105 ｜ function:get_production_status@124
- **flex_fab_agent/tools/registry.py** — 14 符号
  - variable:_TOOLS_NEED_TOKEN@25 ｜ class:ToolSchema@29 ｜ class:ToolRegistry@46 ｜ method:__init__@55 ｜ method:register@61 ｜ method:register_mcp@73
  - method:get_tool_defs@78 ｜ method:get_schema@92 ｜ method:list_all@95 ｜ method:execute@98 ｜ method:__len__@177 ｜ method:__repr__@180
  - function:build_default_registry@188 ｜ function:_search_kb@258
- **flex_fab_agent/tools/resource_tools.py** — 3 符号
  - function:query_inventory@14 ｜ function:query_machine_load@39 ｜ function:query_customer@54
- **flex_fab_agent/tools/sandbox.py** — 4 符号
  - class:ToolExecutionError@42 ｜ method:__init__@44 ｜ function:run_with_retry@51 ｜ function:_run@80
- **flex_fab_agent/tools/scheduler_tools.py** — 28 符号
  - variable:_PLACEHOLDER_M4B@33 ｜ variable:_PLACEHOLDER_M5@34 ｜ function:run_scheduling@37 ｜ function:query_schedule@83 ｜ function:query_sim_events@109 ｜ function:approve_schedule@132
  - function:query_load_assessment@189 ｜ function:query_ctp@235 ｜ function:query_order_tracking@273 ｜ function:_ahead_orders@322 ｜ function:query_preprocess_load@342 ｜ function:_kpi_on_time@360
  - function:_kpi_delay_total@370 ｜ function:_kpi_cabin_utilization@384 ｜ function:_kpi_done_parts@405 ｜ function:_kpi_yield_rate@414 ｜ function:kpi_metrics@421 ｜ function:query_kpi@490
  - function:query_forecast@514 ｜ function:_yield_bad_rows@538 ｜ function:_done_parts_by_machine@547 ｜ function:_machine_failure_counts@564 ｜ function:_yield_rule_based_advice@583 ｜ function:_yield_advice@604
  - function:query_yield@625 ｜ function:_placeholder@673 ｜ function:_handler@674 ｜ variable:PLACEHOLDER_TOOLS@679
- **web/src/api/config.ts** — 3 符号
  - constant:http@4 ｜ function:fetchConfig@17 ｜ function:saveConfig@22
- **web/src/api/dashboard.ts** — 4 符号
  - constant:http@4 ｜ function:fetchKpiHistory@45 ｜ function:fetchCosts@50 ｜ function:fetchTraces@55
- **web/src/api/debug.ts** — 9 符号
  - constant:http@6 ｜ function:askTrace@56 ｜ function:fetchCases@61 ｜ function:fetchTrace@69 ｜ function:rerunCase@74 ｜ function:judgeCase@79
  - function:labelCase@84 ｜ function:fetchStats@89 ｜ function:fetchAdminToken@94
- **web/src/api/log.ts** — 2 符号
  - constant:http@3 ｜ function:fetchLogs@36
- **web/src/api/resources.ts** — 3 符号
  - constant:http@3 ｜ function:fetchResources@7 ｜ function:setPersonnelStatus@13
- **web/src/api/schedule.ts** — 3 符号
  - constant:http@3 ｜ function:fetchVersions@13 ｜ function:approveSchedule@18
- **web/src/views/CasesView.vue** — 18 符号
  - constant:loading@105 ｜ constant:error@106 ｜ constant:cases@107 ｜ constant:stats@108 ｜ constant:typeFilter@109 ｜ constant:goodFilter@110
  - constant:adminToken@111 ｜ constant:drawer@112 ｜ constant:replayLoading@113 ｜ constant:replayId@114 ｜ constant:replay@115 ｜ constant:rateText@117
  - function:saveToken@120 ｜ function:typeTag@124 ｜ function:load@128 ｜ function:mark@145 ｜ function:rerun@159 ｜ function:openReplay@173
- **web/src/views/ConfigView.vue** — 10 符号
  - constant:loading@48 ｜ constant:saving@49 ｜ constant:error@50 ｜ constant:msg@51 ｜ constant:cfg@52 ｜ constant:adminToken@53
  - constant:switches@54 ｜ function:saveToken@56 ｜ function:load@60 ｜ function:save@75
- **web/src/views/DashboardView.vue** — 12 符号
  - constant:loading@63 ｜ constant:error@64 ｜ constant:kpiData@65 ｜ constant:costModels@66 ｜ constant:traceData@67 ｜ constant:kpiChartEl@69
  - constant:costChartEl@70 ｜ variable:kpiChart@71 ｜ variable:costChart@72 ｜ function:renderKpiChart@74 ｜ function:renderCostChart@98 ｜ function:resizeCharts@110
- **web/src/views/DebugView.vue** — 24 符号
  - constant:emit@113 ｜ constant:instance@114 ｜ constant:router@115 ｜ function:goDemo@118 ｜ constant:query@123 ｜ constant:loading@124
  - constant:error@125 ｜ constant:result@126 ｜ constant:adminToken@127 ｜ constant:judging@128 ｜ constant:judgeError@129 ｜ constant:judge@130
  - constant:detail@132 ｜ constant:detailVisible@133 ｜ constant:detailJson@134 ｜ function:pretty@136 ｜ function:openDetail@143 ｜ function:buildTree@155
  - constant:traceTree@169 ｜ constant:judgeEntries@171 ｜ function:saveToken@177 ｜ function:copyToken@181 ｜ function:submit@202 ｜ function:runJudge@218
- **web/src/views/DemoCasesView.vue** — 7 符号
  - constant:demoSteps@9 ｜ constant:groups@26 ｜ constant:emit@139 ｜ constant:instance@140 ｜ constant:router@141 ｜ function:goTab@144
  - function:copyAsk@150
- **web/src/views/LogView.vue** — 14 符号
  - constant:page@6 ｜ constant:pageSize@7 ｜ constant:total@8 ｜ constant:items@9 ｜ constant:loading@10 ｜ constant:category@12
  - constant:dateRange@13 ｜ constant:keyword@14 ｜ function:fmtTime@16 ｜ function:load@20 ｜ function:onSearch@43 ｜ function:onReset@48
  - constant:categoryTag@56 ｜ constant:categoryLabel@62
- **web/src/views/OverviewView.vue** — 10 符号
  - constant:heroStats@5 ｜ constant:pains@13 ｜ constant:flowSteps@19 ｜ constant:abilities@28 ｜ constant:reliability@35 ｜ function:goManual@42
  - constant:layers@46 ｜ constant:highlights@55 ｜ constant:versionLine@61 ｜ constant:emit@67
- **web/src/views/PortalView.vue** — 4 符号
  - constant:activeTab@13 ｜ constant:dashboardRef@14 ｜ function:onTabChange@16 ｜ function:onSwitchTab@24
- **web/src/views/ResourcesView.vue** — 10 符号
  - constant:categories@6 ｜ constant:active@16 ｜ constant:items@17 ｜ constant:loading@18 ｜ constant:error@19 ｜ constant:togglingId@20
  - constant:columns@22 ｜ function:load@24 ｜ function:switchTab@38 ｜ function:toggleStatus@43
- **web/src/views/ScheduleView.vue** — 6 符号
  - constant:versions@7 ｜ constant:loading@8 ｜ constant:adminToken@9 ｜ function:load@11 ｜ function:saveToken@22 ｜ function:act@27
- **web/vite.config.ts** — 1 符号
  - constant:apiTarget@7
