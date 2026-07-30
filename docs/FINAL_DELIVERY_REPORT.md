# SafeChat-Guard V3 Final Delivery Report

## 1. 交付范围

正式代码基线为合并提交 `dbd849bca25d53f8a7b4e3e603a9d1fd5a9834e3`。本轮仅完善真实LLM启动与冒烟验收、运行文档、需求追踪和预训练模型合规说明；没有修改V3模型、阈值、规则、Normalizer、ActionRouter或Pipeline决策逻辑。

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
| 合并前测试基线 | 573 passed |
| 本轮最终测试 | 576 passed |

这些指标来自项目自建 `internal_holdout`，只用于内部冻结验收，不代表官方隐藏测试结果。该holdout只正式运行一次，运行后未调整模型、阈值、规则或评估代码，也未重跑。

## 4. 真实LLM交付

默认 `config.yaml` 仍使用mock，不产生网络请求。真实上游使用独立的 `config.real_llm.example.yaml`，API通过 `SAFECHAT_CONFIG_PATH` 显式选择配置；密钥只从 `DASHSCOPE_API_KEY` 环境变量读取。

`scripts/smoke_real_llm.py`用于获授权环境的真实链路演示。它验证：

- pass请求调用真实上游；
- block请求调用计数不增加；
- sanitize请求发送内容等于Pipeline脱敏结果，且不含原手机号；
- 注入上游异常时返回安全服务错误；
- 注入违规模型输出时OutputGuard拦截且不回传原文。

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

V3可作为当前规则+轻量语义基线和真实LLM安全代理交付。答辩和报告必须准确标注轻量分类器性质及内部指标来源。不要在冻结V3分支仓促加入预训练模型；建议将其作为V4可选适配器，完成许可证、离线制品、资源预算和独立验证后再启用。