# SafeChat-Guard V3 Final Delivery Report

## 1. 交付范围

本次纯文档修复前的正式代码基线为合并提交 `93105e56195ec4be338b58780147e65f88c9b8c9`（短哈希 `93105e5`）。本轮仅修复交付文档口径；没有修改V3模型、阈值、规则、Normalizer、ActionRouter、Pipeline决策逻辑、测试或评估文件。

## 2. 系统能力

系统采用纵深防御：

1. Normalizer生成检测视图，处理常见空格、符号和变体；
2. RuleFilter执行四类词库和正则第一层检测；
3. SemanticClassifier执行第二层概率分类；
4. ActionRouter/V3路由输出 `pass`、`sanitize` 或 `block`；
5. sanitize必须改写并复检，残余风险按安全策略升级；
6. block不调用LLM，pass或通过复检的sanitize才调用上游；
7. OutputGuard对模型回复再次检测、脱敏或拦截；
8. EventLogger记录脱敏后的阶段事件和请求级摘要，并提供每日统计和类别占比。

当前语义层是scikit-learn Pipeline中的 **TF-IDF + LogisticRegression** 轻量分类器。它不是开源预训练Transformer文本分类模型；详细字面合规差距见 `PRETRAINED_MODEL_COMPLIANCE_AUDIT.md`。

## 3. V3冻结评估

一次性内部留出集共330条，冻结结果如下：

| 指标 | 结果 |
|---|---:|
| Accuracy | 99.39% |
| Block Recall | 100% |
| Sanitize Recall | 100% |
| Normal FPR | 1.54% |
| 生产一致性矩阵 | 170/170 |
| 修复前代码基准最终公开测试 | 576 passed |

这些指标来自项目自建 `internal_holdout`，只用于内部冻结验收，不代表官方隐藏测试结果。该holdout只正式运行一次，运行后未调整模型、阈值、规则或评估代码，也未重跑。

## 4. 真实LLM交付

默认 `config.yaml` 仍使用 mock，不产生网络请求。真实上游使用独立的 `config.real_llm.example.yaml`，API 通过 `SAFECHAT_CONFIG_PATH` 显式选择配置；密钥只从 `DASHSCOPE_API_KEY` 环境变量读取。

2026-07-31 已完成真实 Qwen 联网验证：provider=`qwen`、model=`qwen-plus`、status=`passed`，真实上游调用 2 次。验收结果为 `pass_forwarded=true`、`block_not_forwarded=true`、`sanitize_forwarded_after_redaction=true`、`upstream_failure_closed_safely=true`、`unsafe_output_blocked=true`。验收输出未打印凭据（`credentials_printed=false`），运行后已清除进程环境变量 `DASHSCOPE_API_KEY`。报告不记录 API key、Authorization 头、提示词或模型原始回答。

`scripts/smoke_real_llm.py` 已用于本次获授权环境的真实链路验收。验收场景包括：

- pass请求调用真实上游；
- block请求调用计数不增加；
- sanitize请求发送内容等于Pipeline脱敏结果，且不含原手机号；
- 本地注入式上游异常返回安全服务错误（该场景不是 DashScope 真实故障）；
- 本地注入式违规模型输出由 OutputGuard 拦截且不回传原文。

脚本成功输出不包含prompt、response或key。真实调用需要供应商账号、网络、模型权限，且可能计费；本仓库不包含任何凭据。

## 5. API和界面

- 正式HTTP入口：`python api_server.py`
- 兼容入口：`python app.py`
- Streamlit：`streamlit run frontend/streamlit_app.py`
- 聊天：`POST /api/chat`
- 仅检测：`POST /api/detect`
- 运行状态：`GET /health`、`GET /ready`
- 规则CRUD/导入：`/api/rules*`
- 每日统计：`/api/stats/summary`、`/api/stats/daily`

Streamlit默认仍使用mock配置，适合离线答辩；真实LLM演示使用HTTP API入口，避免误产生外部调用。

## 6. 安全和隐私边界

- 高风险输入在模型调用前终止；
- sanitize改写失败、无变化或复检失败时安全升级；
- 上游失败不暴露异常正文、凭据或模型原文；
- 风险输出不返回 `raw_reply` 或 `model_response`；
- 规则管理需要loopback或管理员token；
- 请求日志只保留脱敏审计字段；
- 私有holdout CSV和逐条指标不属于公开交付。

## 7. 已知限制

- 当前语义层不满足“开源预训练文本分类模型”的严格字面要求；
- 真实LLM依赖外部网络、配额、区域和供应商可用性；
- 示例endpoint和模型名可能随供应商服务调整，部署时应核对官方文档；
- 内部留出集不能替代官方测试或真实流量监控；
- 新增预训练适配器若启用会改变语义证据分布，必须作为后续版本独立校准，不能复用当前holdout调参。

## 8. 发布建议

V3可作为当前规则+轻量语义基线及已完成真实 Qwen 联网验收的安全接入代码交付。答辩和报告必须准确标注轻量分类器性质、内部指标来源及联网验收边界；S13 是本地注入式安全路径测试，不是 DashScope 真实故障。不要在冻结V3分支仓促加入预训练模型；建议将其作为V4可选适配器，完成许可证、离线制品、资源预算和独立验证后再启用。