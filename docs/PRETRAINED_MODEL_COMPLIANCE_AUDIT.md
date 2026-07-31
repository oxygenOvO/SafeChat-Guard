# Pretrained Model Compliance Audit

## 审计范围与结论

本报告只读审查以提交 `93105e56195ec4be338b58780147e65f88c9b8c9`（短哈希 `93105e5`）为修复前代码基准，没有为预训练模型修改代码、配置或依赖。结论是：当前V3 **不严格满足**“使用开源预训练文本分类模型”的字面要求。现有语义模型由项目自建数据训练，属于 **TF-IDF + LogisticRegression** 轻量监督分类器，具体实现为scikit-learn `TfidfVectorizer` 与 `LogisticRegression` Pipeline；它不是下载并适配的开源预训练语言模型或Transformer分类模型。

这不否定当前规则、轻量语义、动作路由和内部评估结果，但交付材料必须明确限制，不能把现有joblib模型描述为“预训练Transformer”。

## 1. 当前可扩展接口

- `SemanticClassifier.detect(text) -> list[Detection]`提供稳定检测契约；
- `SemanticClassifier.status()`提供loaded、model hash、classes和阈值状态；
- `semantic_config.py`集中解析模型路径、SHA256、类别阈值和margin；
- `build_semantic_classifier`是Pipeline创建分类器的工厂边界；
- `SafeChatPipeline._scan_text_layers`只消费Detection列表，不依赖sklearn内部类型；
- `semantic.required`支持可选降级或启动失败；
- 模型文件SHA256校验已经形成供应链完整性基础。

因此可以在不改ActionRouter和Pipeline决策逻辑的前提下，让新适配器实现相同 `detect/status` 契约。

## 2. 可选预训练适配器预计改动

建议仅在后续独立版本中修改：

| 文件/区域 | 预计改动 |
|---|---|
| `safechat_guard/pretrained_classifier.py`（新增） | tokenizer、模型推理、标签映射、批量/设备管理、确定性状态 |
| `safechat_guard/semantic_config.py` | 增加显式backend选择和严格schema，不静默替换当前backend |
| `config/semantic_thresholds_*.json` | 独立模型标识、revision、许可证、制品hash、标签和阈值 |
| `requirements.txt`或可选requirements | 固定transformers/torch或onnxruntime/tokenizers版本 |
| `scripts/fetch_pretrained_model.py`（可选） | 受控下载、revision锁定、hash和许可证确认；不在应用启动时下载 |
| `tests/test_pretrained_classifier.py`（新增） | 离线加载、标签映射、错误关闭、hash、CPU行为和无网络测试 |
| README/OPERATIONS/NOTICE | 来源、许可证、体积、离线部署、资源和回滚说明 |

不建议为接入适配器修改Normalizer、ActionRouter或现有V3阈值。

## 3. 依赖、体积与运行风险

- 依赖：常见方案需要 `transformers`、`tokenizers`、`torch`，或导出后使用 `onnxruntime`；还可能需要SentencePiece。
- 体积：中文文本分类模型通常从数百MB到超过1GB，另有运行时依赖和缓存；Git直接交付通常不合适。
- 许可证：必须分别核对模型权重、基础模型、数据集和代码许可证，记录精确revision；“可下载”不等于可再分发或可商用。
- 下载：首次启动在线下载会引入不可复现、超时、供应链和比赛现场断网风险；应预下载、锁revision、校验SHA256并准备制品清单。
- 离线：需要验证无网络加载、缓存目录、Windows/Linux路径、CPU内存、启动时间和并发延迟。
- 行为：标签空间和置信度不可直接套用当前sklearn阈值；需要仅用train/dev重新映射与校准。

## 4. 三小时可行性

三小时内可以完成“能加载并返回Detection”的原型，但不能安全完成生产级交付。严格合规还需要模型选择与许可证审查、受控下载、离线打包、标签映射、资源测试、dev校准、回归和故障关闭验证。这些工作在三小时内压缩完成会产生不可接受的许可证、供应链和效果回归风险。

## 5. 对当前V3结果的影响

- 适配器保持默认关闭：当前V3结果和生产行为不变。
- 适配器启用：语义detections、概率分布和动作路由输入会变化，因此当前V3指标不能直接继承。
- 任何新backend都只能使用train训练/适配、dev选择阈值；不得查看或重复运行已冻结internal_holdout。
- 若需要正式比较，应建立新的、事先冻结的评估协议和新数据，不得用当前holdout调参。

## 6. 最终建议

不建议在当前冻结V3中临时接入新模型；应在最终报告中明确说明字面合规限制。把预训练模型作为V4的可选适配器：保持现有sklearn后端为可回滚基线，先完成许可证和离线制品审查，再用train/dev开发与校准，最后采用新的预注册评估流程验收。

理由：当前V3已经冻结且效果稳定；临近交付加入大体积新依赖会改变语义证据分布，并带来下载、许可证、资源和跨平台风险。诚实披露限制比在缺乏完整验证时宣称满足要求更安全、可审计。