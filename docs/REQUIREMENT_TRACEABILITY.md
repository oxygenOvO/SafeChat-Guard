# SafeChat-Guard Requirement Traceability

## 证据说明

下表使用最终统一截图编号 S01-S16，把题目能力映射到实现文件、API/界面和自动测试。S12、S13 已按 2026-07-31 验收事实采集，其余截图仍待人工采集。截图不得包含 API key、管理员 token、`Authorization` 头、提示词、模型原始回答、用户隐私、internal holdout 文本或逐条预测。

| 截图编号 | 题目要求 | 实现文件 | API/界面 | 测试或公开证据 | 截图状态 |
|---|---|---|---|---|---|
| S01 | 系统主页 | `frontend/streamlit_app.py`、`api_server.py`、`templates/`、`static/` | 系统主页、Streamlit 首页 | `tests/test_frontend_smoke.py`、`tests/test_frontend_adapter.py`、`tests/test_http_api_integration.py` | 待人工采集 |
| S02 | 正常内容 pass | `safechat_guard/pipeline.py`、`safechat_guard/action_router_v3.py` | 聊天页、`POST /api/chat` | `tests/test_pipeline.py`、`tests/test_pipeline_action_router.py`、`tests/test_action_router_v3.py` | 待人工采集 |
| S03 | 低风险 sanitize | `safechat_guard/sanitizer.py`、`safechat_guard/pipeline.py` | 聊天页、`POST /api/chat` 的改写与复检结果 | `tests/test_pipeline.py`、`tests/test_pipeline_action_router.py` | 待人工采集 |
| S04 | 高风险 block 且不转发模型 | `safechat_guard/pipeline.py`、`safechat_guard/action_router_v3.py` | `POST /api/chat` 的 `model_forwarded=false` | `tests/test_pipeline_action_router.py`、`tests/test_real_llm_smoke.py` | 待人工采集 |
| S05 | 模型输出二次校验 | `safechat_guard/output_guard.py`、`safechat_guard/pipeline.py` | `POST /api/chat` 的 `output_filter` | `tests/test_output_guard.py`、`tests/test_security_invariants.py` | 待人工采集 |
| S06 | 规则新增 | `safechat_guard/rule_manager.py`、`api_server.py` | 规则管理页、`POST /api/rules` | `tests/test_rule_manager.py`、`tests/test_rule_management_api.py` | 待人工采集 |
| S07 | 规则删除 | `safechat_guard/rule_manager.py`、`api_server.py` | 规则管理页、`DELETE /api/rules/{id}` | `tests/test_rule_manager.py`、`tests/test_rule_management_api.py` | 待人工采集 |
| S08 | 规则批量导入 | `safechat_guard/rule_manager.py`、`api_server.py` | 规则导入页、`POST /api/rules/import` | `tests/test_rule_manager.py`、`tests/test_rule_management_api.py` | 待人工采集 |
| S09 | 每日违规统计 | `safechat_guard/logger.py`、`api_server.py` | 统计页、`GET /api/stats/daily` | `tests/test_logger_stats_v2.py`、`tests/test_rule_management_api.py` | 待人工采集 |
| S10 | 违规类型占比 | `safechat_guard/logger.py`、`frontend/streamlit_app.py` | 统计页、`GET /api/stats/summary` | `tests/test_logger_stats_v2.py`、`tests/test_frontend_adapter.py` | 待人工采集 |
| S11 | health/ready 状态 | `api_server.py`、`safechat_guard/semantic_classifier.py` | `GET /health`、`GET /ready` | `tests/test_http_api_integration.py`、`tests/test_semantic_runtime_config.py` | 待人工采集 |
| S12 | 真实 LLM 正常调用 | `safechat_guard/llm_client.py`、`config.real_llm.example.yaml`、`scripts/smoke_real_llm.py` | `GET /ready`、`POST /api/chat`、冒烟脚本摘要 | 2026-07-31：provider=`qwen`、model=`qwen-plus`、真实调用 2 次、status=`passed`、`pass_forwarded=true`、`sanitize_forwarded_after_redaction=true`；`credentials_printed=false`，运行后已清除 `DASHSCOPE_API_KEY` | 已采集（真实 Qwen 联网成功） |
| S13 | 真实 LLM 上游异常安全处理 | `safechat_guard/llm_client.py`、`safechat_guard/pipeline.py`、`scripts/smoke_real_llm.py` | `POST /api/chat` 的安全 503/`llm_unavailable`、冒烟脚本受控异常摘要 | `block_not_forwarded=true`、`upstream_failure_closed_safely=true`、`unsafe_output_blocked=true`；上游异常和违规输出均为本地注入式安全路径测试，不代表 DashScope 真实故障 | 已采集（注入式安全处理） |
| S14 | 576 项公开测试通过 | `tests/`、`requirements-dev.txt` | pytest 终端汇总 | 修复前代码基准：`576 passed`，不包含重新运行 internal holdout | 待人工采集 |
| S15 | V3 公开聚合指标 | `reports/performance_v3/public_release_evidence_v3.json` | 公开聚合证据的只读视图 | `tests/test_filter_effect_constraints_v3.py`、`tests/test_performance_dataset_v3.py` | 待人工采集 |
| S16 | 生产一致性 170/170 | `scripts/check_production_equivalence_v3.py`、`reports/performance_v3/PRODUCTION_EQUIVALENCE_REPORT.md` | 生产一致性报告的只读视图 | `tests/test_production_equivalence_v3.py` | 待人工采集 |

## 指标口径

V3 的 Accuracy 99.39%、Block Recall 100%、Sanitize Recall 100%、Normal FPR 1.54% 来自 330 条自建、一次性运行的内部留出集，不是官方隐藏测试结果。internal holdout 只正式运行一次，运行后未调参、未重跑。生产一致性 170/170 说明冻结 V3 直接入口与生产入口在公开矩阵上一致，不等同于泛化性能证明。

默认 mock 模式只用于离线演示和自动测试，不构成真实联网证据。2026-07-31 已完成 provider=`qwen`、model=`qwen-plus` 的真实联网验收，真实调用 2 次且 status=`passed`；S12、S13 已采集。S13 只证明本地注入条件下的安全关闭和输出拦截路径，不表示 DashScope 发生过真实故障。