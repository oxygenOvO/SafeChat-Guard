# SafeChat-Guard Requirement Traceability

## 证据说明

下表把题目能力映射到代码、API/界面和自动测试。“截图编号”是最终答辩截图清单编号；仓库当前不提交截图二进制，采集时不得包含API key、用户隐私、holdout文本或逐条预测。自动测试是当前主要可重复证据。

| 题目要求 | 实现模块 | API/界面 | 测试文件 | 截图编号 | 当前状态 |
|---|---|---|---|---|---|
| 四类违规词库 | `data/lexicons/{ad,porn,violence,sensitive}.txt`、`RuleFilter` | 检测页、`POST /api/detect` | `tests/test_rule_filter.py`、`tests/test_final_delivery_adversarial.py` | S01 | 已实现并测试；截图待采集 |
| 规则CRUD和导入 | `RuleManager`、`dispatch_management_*` | Streamlit规则页、`/api/rules*` | `tests/test_rule_management_api.py`、`tests/test_rule_manager.py` | S02 | 已实现并测试；截图待采集 |
| 关键词+正则第一层 | `RuleFilter`、`data/rules/regex_rules.json` | `POST /api/detect` detections | `tests/test_rule_filter.py`、`tests/test_pipeline.py` | S03 | 已实现并测试；截图待采集 |
| 语义分类第二层 | `SemanticClassifier`、`semantic_config.py` | `/ready`、检测结果中的 `semantic_ml` | `tests/test_semantic_classifier.py`、`tests/test_semantic_runtime_config.py` | S04 | 已实现；TF-IDF+LogisticRegression，非预训练Transformer |
| pass/sanitize/block | `ActionRouter`、`ActionRouterV3` | 聊天页、`POST /api/chat` | `tests/test_pipeline_action_router.py`、`tests/test_action_models_v3.py` | S05 | 已实现并测试；截图待采集 |
| 高风险不调用LLM | `SafeChatPipeline.handle_chat` block短路 | `/api/chat` 的 `model_forwarded=false` | `tests/test_pipeline_action_router.py`、`tests/test_real_llm_smoke.py` | S06 | 已实现并测试；截图待采集 |
| sanitize后复检 | `Sanitizer`、`SafeChatPipeline._filter_text` | `/api/chat` 的 `rewrite_recheck` | `tests/test_pipeline.py`、`tests/test_pipeline_action_router.py` | S07 | 已实现并测试；截图待采集 |
| 输出二次校验 | `OutputGuard`、`SafeChatPipeline._filter_output` | `/api/chat` 的 `output_filter` | `tests/test_output_guard.py`、`tests/test_security_invariants.py` | S08 | 已实现并测试；截图待采集 |
| 日志记录 | `EventLogger`、`request_summary` | 日志页、`data/logs/events.jsonl` | `tests/test_output_guard.py`、`tests/test_pipeline_action_router.py` | S09 | 已实现并测试；截图待采集 |
| 每日统计和类别占比 | `EventLogger.daily_stats` | 统计页、`/api/stats/summary`、`/api/stats/daily` | `tests/test_logger_stats_v2.py`、`tests/test_rule_management_api.py` | S10 | 已实现并测试；截图待采集 |
| 真实LLM调用 | `OpenAICompatibleLLMClient`、`config.real_llm.example.yaml`、`smoke_real_llm.py` | `/ready`、`POST /api/chat` | `tests/test_llm_client.py`、`tests/test_real_llm_smoke.py` | S11 | 可演示；需授权key和网络，截图待采集 |
| 测试和运行说明 | `README.md`、`docs/OPERATIONS.md` | 命令行、API、Streamlit | 全量 `tests/` | S12 | 文档已补齐；576 passed，compileall与diff-check通过 |

## 截图采集清单

- S01：四类词库命中概览，不展示私有文本。
- S02：规则列表与dry-run导入结果，隐藏pattern和管理员token。
- S03：关键词/正则detections及风险动作。
- S04：`/ready`语义模型已加载、类型如实标注为sklearn pipeline。
- S05：pass、sanitize、block三联结果。
- S06：block结果中的 `model_forwarded=false`。
- S07：sanitize改写与复检状态，不展示原始隐私值。
- S08：违规模型输出被OutputGuard拦截。
- S09：脱敏后的请求摘要日志。
- S10：每日数量与类别占比图。
- S11：真实provider ready及冒烟脚本成功摘要，不含请求、回复或key。
- S12：pytest、compileall、diff-check最终通过摘要。

## 指标口径

V3的Accuracy 99.39%、Block Recall 100%、Sanitize Recall 100%、Normal FPR 1.54%来自330条自建一次性内部留出集，不是官方隐藏测试结果。internal_holdout只运行一次，运行后未调参。生产一致性170/170说明冻结V3直接入口与生产入口在公开矩阵上一致，不等同于泛化性能证明。