# SafeChat-Guard V3 Final Delivery Report

## 1. 交付范围

最终竞赛提交冻结版本为 `1286f3db3e5e73f6ad7543cdbd47ed9227235b5c`（短哈希 `1286f3d`）。`93105e5` 是 earlier/pre-final delivery baseline。本轮仅修复交付文档口径；没有修改 V3 模型、阈值、规则、Normalizer、ActionRouter、Pipeline 决策逻辑、测试或评估文件。

## 2. 系统能力

系统采用纵深防御：

1. Normalizer生成检测视图，正式处理 Unicode/控制字符、符号插入、Emoji、同音、拼音、缩写、重复噪声和受控拆分；
2. RuleFilter执行四类词库和正则第一层检测；
3. SemanticClassifier执行第二层概率分类；
4. ActionRouter/V3路由输出 `pass`、`sanitize` 或 `block`；
5. 输入 sanitize 由 ActionRouterV3 判定；Sanitizer 对 normalized text 中已定位的 match 做局部改写并复检，残余风险按安全策略升级；
6. block不调用LLM，pass或通过复检的sanitize才调用上游；
7. OutputGuard使用基础扫描证据、独立 80/40 阈值、privacy regex 和 extra high-risk rules 对模型回复脱敏或拦截；
8. EventLogger记录脱敏后的阶段事件和请求级摘要，并提供每日统计和类别占比。

当前语义层是scikit-learn Pipeline中的 **TF-IDF + LogisticRegression** 轻量分类器。它不是开源预训练Transformer文本分类模型；详细字面合规差距见 `PRETRAINED_MODEL_COMPLIANCE_AUDIT.md`。

V3 预留 `variant_char` 形近字扩展接口，但冻结版本的 `data/maps/variant_char_map.json` 为空，未将形近字恢复作为正式启用能力。输入 Sanitizer 是 match-driven 局部替换器：对“加微信”“联系微信”等已定位联系方式 match 使用联系方式隐藏占位，其他传入 match 使用通用替换；它自身不提供手机、固定电话、邮箱、微信号、身份证、银行卡和地址到 `[REDACTED]`、`[PRIVACY]`、`[AD]` 的完整结构化字段体系。

结构化隐私处理属于输出侧 OutputGuard，源码覆盖 phone、email、id_card、bank_card、url、ip、wechat、qq、address。输出侧不会把模型输出重新完整送入 ActionRouterV3；它以基础扫描 detection 为证据之一，再叠加隐私正则和输出高风险规则进行独立处置。核心训练/输入风险标签仍为 `normal/ad/porn/violence/sensitive`；`privacy/illegal/self_harm` 等属于输出运行时扩展类别，`abuse` 具有输出侧标签和安全响应支持。

## 3. V3冻结评估

一次性内部留出集共330条，冻结结果如下：

| 指标 | 结果 |
|---|---:|
| Accuracy | 99.39% |
| Block Recall | 100% |
| Sanitize Recall | 100% |
| Normal FPR | 1.54% |
| 生产一致性矩阵 | 170/170 |
| 最终竞赛冻结提交公开测试 | 594 passed |
| earlier/pre-final delivery baseline | 576 passed |

这些指标来自项目自建 `internal_holdout`，只用于内部冻结验收，不代表官方隐藏测试结果。该holdout只正式运行一次，运行后未调整模型、阈值、规则或评估代码，也未重跑。

最终测试来自 `1286f3d` 的干净 frozen clone：`594 collected`；执行结果为 `594 passed, 1297 warnings in 79.27s`。生产一致性 170/170 只证明公开非 holdout 用例上的直接入口与生产入口一致，不证明真实世界泛化率。200 条 Gold 当前为 provisional single-review gold；第二 reviewer 的 40 条 blind sample 尚未完成时，不称双人独立审核完成。

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
- `variant_char` 接口存在但冻结映射为空，形近字恢复未正式启用；
- 真实LLM依赖外部网络、配额、区域和供应商可用性；
- 示例endpoint和模型名可能随供应商服务调整，部署时应核对官方文档；
- 内部留出集不能替代官方测试或真实流量监控；
- 新增预训练适配器若启用会改变语义证据分布，必须作为后续版本独立校准，不能复用当前holdout调参。
- 报告记录的 Mean 35.21 ms、P50 28.88 ms、P95 79.92 ms、Throughput 28.36 req/s 属于冻结前本机性能实验；冻结 Git commit 内尚缺与这些精确数字直接绑定的完整 benchmark artifact。后续复现只能使用公开 dev 数据并单独标记，不得接触 internal holdout。

## 8. 发布建议

V3可作为当前规则+轻量语义基线及已完成真实 Qwen 联网验收的安全接入代码交付。答辩和报告必须准确标注轻量分类器性质、内部指标来源及联网验收边界；S13 是本地注入式安全路径测试，不是 DashScope 真实故障。不要在冻结V3分支仓促加入预训练模型；建议将其作为V4可选适配器，完成许可证、离线制品、资源预算和独立验证后再启用。
