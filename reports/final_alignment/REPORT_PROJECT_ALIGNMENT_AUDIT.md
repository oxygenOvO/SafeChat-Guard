# SafeChat-Guard Final Report / Project Alignment Audit

> 本文件保留文档修复前的审计快照与原始结论；本分支的文档对齐修复状态见 `docs/REPORT_ALIGNMENT_NOTES.md`。

## 1. 审计基线

- 审计日期：2026-08-11（Asia/Shanghai）
- 仓库：当前 Git 仓库根目录
- 当前分支：`docs/report-project-alignment-v1`
- 当前 HEAD：`1286f3db3e5e73f6ad7543cdbd47ed9227235b5c`
- `origin/main`：`1286f3db3e5e73f6ad7543cdbd47ed9227235b5c`
- 最终竞赛提交冻结提交：`1286f3db3e5e73f6ad7543cdbd47ed9227235b5c`（`1286f3d`）
- 作品报告审计对象：仓库根目录未跟踪文件 `作品报告v4.docx`。该文件不属于冻结 Git tree；本审计将其作为待对齐的作品报告文本，而不把它当作冻结代码证据。
- 冻结边界：本次未修改或执行任何模型、阈值、规则、映射、词表、数据集、评估结果或核心实现；未运行 internal holdout；未查看 holdout 原文或逐条预测。

### 1.1 允许读取的公开证据

- `reports/performance_v3/public_release_evidence_v3.json`
- `reports/performance_v3/PRODUCTION_EQUIVALENCE_REPORT.md`
- `reports/manual_review/semantic_gold_v1_manifest.json`
- `config/semantic_thresholds_v1.json`
- `config/action_thresholds_v3.json`

### 1.2 状态与风险定义

- `MATCH`：报告声明与冻结实现/公开证据一致。
- `PARTIAL`：主结论方向正确，但省略了会影响理解或复现的重要条件。
- `MISMATCH`：报告把未实现能力描述为已实现，或把能力归属于错误组件。
- `DOCUMENTATION_STALE`：仓库交付文档仍绑定 earlier baseline，未表达最终冻结口径。
- `EVIDENCE_GAP`：存在结果声明，但最终冻结 Git tree 缺少直接绑定、可机器复核的结果制品或完整复现链。
- `P0`：答辩/真实性风险；`P1`：文档/复现风险；`P2`：排版/表述风险。

## 2. 总体结论

本审计按 20 个可独立判定的审计项计数：

| 状态 | 数量 |
|---|---:|
| MATCH | 9 |
| PARTIAL | 5 |
| MISMATCH | 2 |
| DOCUMENTATION_STALE | 1 |
| EVIDENCE_GAP | 3 |
| **合计** | **20** |

风险差异计数：P0 3 项、P1 6 项、P2 2 项。最需要优先修正的是形近字能力、输入 Sanitizer 能力归属、OutputGuard 架构口径。V3 核心行为应保持冻结，不应通过改代码来迎合作品报告。

### 2.1 核心声明映射总表

| ID | 审计项 | 状态 | 风险 | 核心证据 |
|---|---|---|---|---|
| A1 | 最终冻结提交为 `1286f3d` | MATCH | — | Git HEAD 与 `origin/main` |
| A2 | 仓库交付文档的最终版本/测试口径 | DOCUMENTATION_STALE | P1 | `README.md`、`docs/FINAL_DELIVERY_REPORT.md`、`docs/REQUIREMENT_TRACEABILITY.md`、`docs/OPERATIONS.md` |
| B1 | 冻结提交收集并通过 594 项测试 | MATCH | — | 干净本地 clone：`594 passed, 1297 warnings in 79.27s` |
| B2 | 当前原工作区可直接复现 pytest | PARTIAL | P1 | 受保护 untracked `codex_v3_stage/tests` 引起同名模块 collection error |
| C1 | 330 条一次性 internal holdout 聚合指标与隔离 | MATCH | — | `public_release_evidence_v3.json` |
| D1 | 170/170 生产链路一致性 | MATCH | — | `PRODUCTION_EQUIVALENCE_REPORT.md` |
| E1 | Gold 200、test 120、blind 40 与单人复核状态 | MATCH | — | `semantic_gold_v1_manifest.json` |
| F1 | TF-IDF + LogisticRegression、五分类与语义阈值 | MATCH | — | `semantic_thresholds_v1.json`、`semantic_classifier.py`、训练/复现脚本 |
| G1 | RiskModel、BlockModel 与 V3 动作阈值 | MATCH | — | `action_models_v3.py`、`action_thresholds_v3.json` |
| G2 | 报告对 ActionRouterV3 完整判定条件的表达 | PARTIAL | P1 | `action_router_v3.py::route` |
| H1 | Unicode、符号、Emoji、同音、拼音、缩写、噪声、重复、受控拆分 | MATCH | — | `normalizer.py`、`normalization/*`、非空映射文件 |
| H2 | 形近字恢复已正式启用 | MISMATCH | P0 | `variant_char_map.json` 为 `{}` |
| I1 | 输入 Sanitizer 的字段级 `[REDACTED]` 能力与执行示例 | MISMATCH | P0 | `sanitizer.py::sanitize`、`pipeline.py::_filter_text` |
| J1 | OutputGuard 与输入侧共用完整 ActionRouterV3 | PARTIAL | P0 | `output_guard.py::OutputGuard`、`pipeline.py::_filter_output` |
| K1 | 五类核心标签与输出侧运行时扩展类别边界 | PARTIAL | P1 | `action_router.py`、`output_guard.py` |
| L1 | 性能数字的最终冻结、可机器复核证据 | EVIDENCE_GAP | P1 | 仅有 untracked `reports/v4_local_performance.json`；冻结 tree 无对应结果文件/精确 benchmark 脚本 |
| M1 | Qwen 配置、脚本逻辑与注入场景边界 | MATCH | — | `config.real_llm.example.yaml`、`scripts/smoke_real_llm.py`、交付文档 |
| M2 | 真实 Qwen 验收的提交内机器结果制品 | EVIDENCE_GAP | P1 | 冻结 tree 有脚本和文档结论，但无独立机器输出制品 |
| P2-1 | 已知页码/编号/重复/行业统计问题在当前 v4 的复核 | EVIDENCE_GAP | P2 | 结构化 DOCX 扫描未复现；缺少当前版本新渲染页面证据 |
| P2-2 | 图表标题与中英文间距一致性 | PARTIAL | P2 | 当前 v4 标题/正文存在空格风格不统一 |

## 3. P0 差异

| ID | 报告声明 | 项目实际实现 | 证据 | 风险 | 建议 |
|---|---|---|---|---|---|
| P0-01 | V3 可识别/恢复形近字；表 2-3 写“形近替换……只在高置信映射中还原”，正文多处把形近列为正式能力 | `TextNormalizer` 确实预留 `variant_char` 阶段，但 `data/maps/variant_char_map.json` 为 `{}`，最终冻结版本没有正式启用非空形近字映射 | `safechat_guard/normalizer.py::TextNormalizer._build_pipeline`；`data/maps/variant_char_map.json` | 把预留接口宣传为已启用能力，答辩真实性风险 | **修作品报告**：统一改为“V3 预留 variant_char/形近扩展接口，但没有正式启用非空形近字映射”。**V3 保持冻结**；非空映射及其验证放入 V4 |
| P0-02 | 2.5 节示例称输入 Sanitizer 将微信号、手机号改写为 `[REDACTED]`；另一示例假设第一次仅删除手机号，复检时才恢复“微★信” | 输入 `Sanitizer.sanitize(text, matches)` 只遍历路由/规则提供的命中词：`加微信`、`联系微信` 替换为 `[联系方式已隐藏]`，其他 match 替换为 `***`。结构化手机号、邮箱、身份证、银行卡、URL、IP、微信、QQ、地址正则属于 OutputGuard。Pipeline 在 sanitize 前已经取得 `normalized`，并调用 `sanitizer.sanitize(normalized, matches)`；因此“先保留变体、复检才首次恢复”的叙述与真实顺序不完全一致 | `safechat_guard/sanitizer.py::Sanitizer.sanitize`；`safechat_guard/pipeline.py::_filter_text`（调用 `sanitize(normalized, matches)`，随后 `_scan_text_layers(rewritten)`）；`safechat_guard/output_guard.py::PRIVACY_PATTERNS/mask_sensitive_info` | 把输出侧能力错误归到输入组件，并给出冻结实现不会按该占位符执行的示例 | **修作品报告**：输入侧只描述基于命中片段的实际替换与复检；结构化隐私正则明确归于 OutputGuard。可把 `[REDACTED]` 示例标为概念示意，或改成真实占位符。**V3 保持冻结** |
| P0-03 | 2.5 节称模型回复进入 OutputGuard 后“执行同样的检测和处置”，整体叙述容易被理解为输入输出共用同一个动作路由 | 输出侧会复用 TextNormalizer、RuleFilter、SemanticClassifier 的基础扫描，但不调用 `ActionRouterV3.route`。`OutputGuard` 自有 `block_threshold=80`、`sanitize_threshold=40`，再叠加隐私正则与 `EXTRA_HIGH_RISK`；sanitize 后还有独立输出复检 | `safechat_guard/pipeline.py::_filter_output`；`safechat_guard/output_guard.py::OutputGuard.__init__/process/mask_sensitive_info/detect_extra_high_risk` | 架构图和答辩若说成“完整共用 ActionRouterV3”，会错误描述冻结实现 | **修作品报告**：写成“输出侧复用基础扫描层，但使用 OutputGuard 独立输出安全判定、隐私正则和扩展高风险规则”。**V3 保持冻结** |

## 4. P1 差异

| ID | 差异 | 证据 | 建议 |
|---|---|---|---|
| P1-01 | 仓库交付文档仍以 `93105e5` 和 `576 passed` 为“修复前/earlier baseline”，但没有同步表达最终竞赛冻结 `1286f3d` 与 `594 passed`；`OPERATIONS.md` 甚至把 576 写成当前预期汇总 | `README.md:7,78`；`docs/FINAL_DELIVERY_REPORT.md:5,33`；`docs/REQUIREMENT_TRACEABILITY.md:S14`；`docs/OPERATIONS.md` 安装验证段 | 下一阶段**修仓库文档**：保留 `93105e5/576` 的历史含义，新增并突出 `1286f3d/594` 是 final competition submission freeze；不要无差别替换历史记录 |
| P1-02 | 当前工作区直接执行 pytest 会把受保护 untracked `codex_v3_stage/tests` 一起收集，造成同名模块冲突；冻结提交本身在干净 clone 中通过 | 原工作区 `--collect-only`：`594 tests collected, 1 error`；原工作区完整命令：17 warnings、1 collection error、0 项执行；干净 clone：594 passed | **修仓库文档/复现说明**：注明最终测试须在干净 checkout/clone 执行。不要删除或移动本地 434 个 untracked 文件 |
| P1-03 | 报告 ActionRouter 概述和动作表说明高风险优先，但没有明确写出完整 V3 block 条件 | `ActionRouterV3.route`：`block_probability >= category_threshold AND evidence_score >= 0.58`，或 `evidence_score >= evidence_block_threshold(0.70)`；另有强规则、严重直接证据、安全语境分支 | **修作品报告**：补充精确伪代码及优先顺序；保持 V3 阈值不变 |
| P1-04 | 报告性能数字在本地 untracked JSON 中可逐项对上，但该 JSON 不属于 `1286f3d`，冻结 tree 也没有与“270 dev / 20 warmup / 1000 detect_text / P50”完全对应的 benchmark 脚本 | untracked `reports/v4_local_performance.json` 含 35.2103682/28.882/79.9242/28.35858 及 snapshot_commit；tracked `scripts/verify_runtime.py` 默认测 `handle_chat`、无 P50、默认 50 次 | 标记 `EVIDENCE_GAP`。如需补证，先经人工批准，在公开 dev 上运行独立 benchmark 并把脚本、环境、输出与 commit 绑定；不涉及 frozen behavior，不读取 holdout |
| P1-05 | 核心训练/判定标签是五类，但 OutputGuard 还有运行时类别；报告对该边界描述较弱 | 核心：`normal/ad/porn/violence/sensitive`。OutputGuard 直接生成 `privacy`，`EXTRA_HIGH_RISK` 直接生成 `illegal/self_harm`；`CATEGORY_LABELS/STANDARD_RESPONSES` 还支持 `abuse`，但当前 `EXTRA_HIGH_RISK` 没有 abuse 词表，不能把 abuse 说成该表直接生成的类别 | **修作品报告**：明确“五类是核心训练/判定标签空间；OutputGuard 额外维护输出安全运行时类别”。准确区分“直接产生”与“可承载/可响应” |
| P1-06 | Qwen 脚本、配置和文档口径一致，但冻结 tree 未包含一次真实验收的独立机器输出文件 | `config.real_llm.example.yaml` 为 qwen/qwen-plus；`smoke_real_llm.py` 真实调用 pass/sanitize 两次，block 不调用；failure/unsafe output 是本地注入；交付文档明确相同边界 | 保留现有谨慎口径。若竞赛要求可复核机器证据，未来在不含密钥、提示词、回复的前提下提交布尔摘要并绑定 commit；不要重跑真实调用来替代本次文档审计 |

## 5. P2 差异

| ID | 检查结果 | 状态 | 建议 |
|---|---|---|---|
| P2-01 | 对当前 `作品报告v4.docx` 的结构化扫描结果：替换字符 `�` 计数 0；“表 2-X”计数 0；“表 3-1”仅 1 次；重复 caption ID 为空；“消融结果进一步表明”计数 0；`15%~20%` 与“超过30%”均未出现。因此这些已知旧问题在当前 v4 文本结构中未复现。标准 DOCX 渲染器因本机缺少 LibreOffice/soffice 无法对最新 v4 重新出图；仓库旧 PNG 早于最新 DOCX，不能证明当前页面 15 的视觉公式无乱码 | EVIDENCE_GAP | 人工用 Word 打开最终 v4，重点复核第 15 页公式与第 34 页编号；若视觉正常，将这些项记为“已修复”。不要根据旧页码盲改当前文档 |
| P2-02 | 当前 v4 中 `SafeChat-GuardV3` 无空格写法计数 0，`SafeChat-Guard V3` 为 19；但图表标题在编号后是否留空格不统一，正文也混用 `ActionRouter动作`/`ActionRouter V3`、`TextNormalizer保留`/`TextNormalizer 保留` 等样式 | PARTIAL | **修作品报告**：统一品牌名、英文术语与中文之间的空格、caption 编号后空格、百分号和 `ms` 单位格式 |

### 5.1 行业统计引用结论

当前 v4 的结构化正文未出现“15%~20%”或“超过30%”，因此当前报告不存在“这两项数字缺引用”的可确认问题。若后续编辑重新加入行业比例，必须给出可核查来源、年份、样本范围和访问日期；否则删除数字化断言。

## 6. 已确认一致项

### 6.1 最终冻结与测试

- `HEAD == origin/main == 1286f3db3e5e73f6ad7543cdbd47ed9227235b5c`。
- 在不含当前 434 个 untracked 文件、但保留 Git 元数据的本地干净 clone 中执行 `python -m pytest -q --basetemp=.test_tmp`：`594 passed, 1297 warnings in 79.27s (0:01:19)`；failed=0，skipped=0。
- warnings 主要为 joblib/NumPy DeprecationWarning、故障/降级路径 RuntimeWarning 和少量资源/日志测试 warning；与作品报告 1297 warnings 的陈述一致。

### 6.2 330 条一次性 internal holdout 聚合证据

`reports/performance_v3/public_release_evidence_v3.json` 直接确认：

- `sample_count=330`；train/dev/holdout=`900/270/330`。
- Accuracy=99.39%，Macro Precision=99.25%，Macro Recall=99.69%，Macro F1=99.46%。
- Block Recall=100%，Sanitize Recall=100%，Normal FPR=1.54%。
- `execution_count=1`、`holdout_run_count=1`、`holdout_rerun=false`、`post_holdout_tuning=false`。
- `holdout_text_included=false`、`per_record_predictions_included=false`。
- raw text hash、normalized text hash、template family 的 train/dev/holdout 两两交集均为 0；高相似跨 split 对数为 0。

正确口径：这是自建、一次性执行的 internal holdout 聚合结果，不是官方测试集，不证明所有真实业务分布上的泛化率。

### 6.3 170/170 生产链路一致性

`reports/performance_v3/PRODUCTION_EQUIVALENCE_REPORT.md` 确认：manual adversarial 40、context boundary 32、generalization 62、safety negative 36，总计 170；Production completed、Action identical、Label identical、No fallback 均为 170/170。

正确口径：170/170 证明 `detect_text` 与生产 `handle_chat` 在这 170 条公开非 holdout 用例上的入口行为一致，不是分类准确率，也不证明真实世界泛化。

### 6.4 Gold 与人工复核

`reports/manual_review/semantic_gold_v1_manifest.json` 确认：

- Gold=200；normal=100，其余 ad/porn/violence/sensitive 各 25。
- pass=100、sanitize=40、block=60。
- calibration=80、test=120；test action 为 pass=60、sanitize=24、block=36。
- blind second review=40，按 label/action 做 deterministic stratified 20% sample。
- reviewers 为 `reviewer_1=200`，状态为 `provisional_single_review_gold`。

正确口径：在第二 reviewer 的 40 条 blind review 未完成前，必须称 **provisional single-review gold（暂定单人复核 Gold）**，不能称已完成双人独立审核。

### 6.5 SemanticClassifier

- 核心标签空间：`normal/ad/porn/violence/sensitive`。
- 模型路径：`models/semantic_model_v2.joblib`；配置 SHA256 与模型文件绑定。
- `config/semantic_thresholds_v1.json`：ad=0.25、porn=0.25、violence=0.55、sensitive=0.65、min_margin=0.05。
- 训练/复现实现使用 scikit-learn `TfidfVectorizer` + `LogisticRegression` Pipeline；不是 Transformer 预训练文本分类模型。
- `docs/PRETRAINED_MODEL_COMPLIANCE_AUDIT.md` 的实质结论正确，但其审计基线仍写 `93105e5`，应在后续文档阶段补充最终冻结上下文，不应改模型迎合要求。

### 6.6 ActionRouterV3

- `safechat_guard/action_models_v3.py` 提供 RiskModel 与 BlockModel 概率。
- `config/action_thresholds_v3.json`：risk_sanitize_threshold=0.70、evidence_block_threshold=0.70；ad/porn/violence/sensitive 的 category block threshold 均为 0.30。
- `ActionRouterV3.route` 的关键 block 条件为：

```text
(block_probability >= category_block_threshold AND evidence_score >= 0.58)
OR evidence_score >= 0.70
```

- 该条件之前还有 legacy strong-rule block、severe direct evidence、safe scope 分支；sanitize 还要求 `risk_probability >= 0.70` 且存在 `risk_entity`，或承接 base sanitize。
- Pipeline 在输入 block 时直接返回，`model_forwarded=false`；sanitize 必须发生实际变化并复检，未变化/空结果/异常或残余风险会安全升级。

### 6.7 Normalizer 的正式能力边界

已确认启用：Unicode NFKC、Cc/Cf 清理、lowercase、Emoji 映射、显式 symbol insertion 映射、noise、repeat、homophone、pinyin、abbreviation、受控 adversarial separator recovery。`variant_char` 仅有扩展阶段，映射为空，不属于正式启用能力。

### 6.8 Qwen 联网验收口径

- 示例配置：provider=`qwen`、model=`qwen-plus`，key 仅来自 `DASHSCOPE_API_KEY`。
- `scripts/smoke_real_llm.py` 的真实 upstream 调用是 pass 与 sanitize，共 2 次；block 不转发。
- `upstream_failure_closed_safely` 与 `unsafe_output_blocked` 使用本地 `FailingClient`/`UnsafeOutputClient` 注入，不是 DashScope 真实故障或真实违规输出事件。
- README、FINAL_DELIVERY_REPORT、REQUIREMENT_TRACEABILITY、OPERATIONS 已正确区分这一边界。

## 7. 报告有、代码弱/没有

1. **正式形近字恢复**：报告多处写成已启用；冻结代码只有空映射扩展接口。
2. **输入侧通用结构化隐私脱敏**：报告的 `[REDACTED]` 手机/微信示例不是 `safechat_guard/sanitizer.py` 的实际通用字段正则行为。
3. **性能机器证据链**：数字在未跟踪 JSON 中存在，但最终冻结 Git tree 缺少精确 benchmark 脚本与提交内结果制品。
4. **真实 Qwen 机器验收制品**：脚本、配置与文档结论存在，独立布尔结果文件未纳入冻结 tree。

## 8. 代码有、报告没有或弱化描述

1. OutputGuard 自有 80/40 阈值，而不是完整调用 ActionRouterV3。
2. OutputGuard 具有 phone/email/id_card/bank_card/url/ip/wechat/qq/address 隐私正则；这些属于输出侧。
3. OutputGuard 的 `EXTRA_HIGH_RISK` 直接扩展 `illegal/self_harm`；隐私正则生成 `privacy`。`abuse` 有展示/拒绝支持，但不是当前 `EXTRA_HIGH_RISK` 直接生成项。
4. ActionRouterV3 的 0.58 联合证据门槛、0.70 独立证据 block 门槛以及 safe-scope/严重直接证据优先分支在报告中表达不足。
5. 输出侧 sanitize 后也会重新扫描；若复检不为 pass，则升级 block。

## 9. 仓库文档过期项

### 9.1 `93105e5` 的正确含义

`93105e5` 在 README、FINAL_DELIVERY_REPORT 和 PRETRAINED_MODEL_COMPLIANCE_AUDIT 中明确写作“本次文档修复前/修复前代码基准”。因此它是 **earlier/pre-final delivery baseline**，不是 final competition submission。不能简单删除全部历史引用；应补充当前最终冻结 `1286f3d` 并把两个阶段分开。

### 9.2 `576 passed` 的正确含义

`576 passed` 是 earlier delivery baseline。最终冻结提交在干净 clone 中实测为 `594 passed`。下列位置需要后续更新：

- `README.md` 基础检查/最终公开测试表述；
- `docs/FINAL_DELIVERY_REPORT.md` V3 冻结评估表；
- `docs/REQUIREMENT_TRACEABILITY.md` S14；
- `docs/OPERATIONS.md` 的“预期汇总”。

更新时应保留说明：`576` 是 earlier baseline，不再是 final submission test count。

## 10. 答辩口径建议

可直接使用以下表述：

1. **语义层**：“当前语义层是 TF-IDF + LogisticRegression 轻量监督分类器，不是 Transformer 预训练分类模型。预训练模型仅作为 V4 候选方向。”
2. **Normalizer 正式能力**：“V3 正式覆盖 Unicode NFKC、控制字符、大小写、符号、Emoji、同音、拼音、缩写、重复/噪声以及受控拆分恢复。”
3. **形近字边界**：“V3 预留 variant_char/形近扩展接口，但最终冻结版本的 variant_char_map 为空，没有正式启用非空形近字恢复。”
4. **输入与输出分工**：“输入侧由 ActionRouterV3 决定 pass/sanitize/block，Sanitizer 根据已定位命中做实际改写并复检；输出侧由 OutputGuard 使用基础扫描、独立 80/40 阈值、隐私正则和输出高风险规则再次处置。”
5. **OutputGuard 架构**：“OutputGuard 复用了归一化、规则和语义基础扫描，但没有完整复用 ActionRouterV3。”
6. **标签空间**：“normal、ad、porn、violence、sensitive 是核心训练/判定五类；OutputGuard 另外维护 privacy、illegal、self_harm 等输出运行时类别。”
7. **330 holdout**：“330 条是项目自建、一次性执行的 internal holdout，不是官方测试集；报告只公开冻结聚合指标。”
8. **170/170**：“170/170 是 production-equivalence，证明直接检测入口和生产对话入口在公开用例上的动作/标签一致，不是泛化准确率。”
9. **Gold**：“200 条 Gold 当前是 provisional single-review gold；第二 reviewer 的 40 条 blind sample 尚未完成时，不称双人独立审核完成。”
10. **测试**：“最终冻结提交 `1286f3d` 在干净 Git clone 中通过 594 项公开自动测试；576 是 earlier delivery baseline。”
11. **Qwen**：“真实 Qwen 调用是 pass 和 sanitize 两次；block 不转发。上游失败和违规输出是本地受控注入测试，不代表 DashScope 发生过真实故障。”
12. **性能**：“35.21 ms 等结果来自本机公开 dev 本地过滤实验，不含 Qwen 网络延迟；当前提交内机器证据链仍需补齐后再作为强复现证据。”

## 11. 建议修复顺序

### 11.1 P0：先修作品报告，不改 V3

1. 删除“V3 已正式实现形近字恢复”的宣传，改为接口预留；V4 再实现非空映射、误报约束与测试。
2. 重写 2.5 节，把输入 Sanitizer 的真实替换行为与 OutputGuard 的结构化隐私正则分开。
3. 重画/改写输入输出架构：输出侧复用基础扫描，但使用独立 OutputGuard，不宣称完整共用 ActionRouterV3。

### 11.2 P1：补复现与交付口径

1. 修仓库文档：保留 `93105e5/576` 的 earlier baseline 含义，补充 `1286f3d/594` final freeze。
2. 补 ActionRouterV3 精确伪代码，明确 0.58/0.70、safe scope、severe evidence 与 sanitize 条件。
3. 在公开 dev 数据上建立经批准的可复现 benchmark 脚本/结果制品；不运行 internal holdout。
4. 若需要强联网证据，提交不含敏感内容的布尔验收摘要并绑定 commit；不把注入场景说成真实故障。
5. 在复现说明中要求干净 checkout/clone，避免本地 untracked 测试副本被 pytest 自动发现。

### 11.3 P2：最终排版核查

1. 用 Word 对最终 DOCX 人工复核第 15 页公式和第 34 页编号；当前结构化扫描未复现旧问题，但缺少最新渲染证据。
2. 统一 caption 编号后空格、中英文边界、品牌名、百分号和时间单位格式。

### 11.4 冻结结论

- **修作品报告**：P0-01、P0-02、P0-03、P1-03、P1-05、P2 项。
- **修仓库文档**：P1-01、P1-02 的复现说明。
- **V3 保持冻结、不修改**：模型、阈值、规则、Normalizer、Sanitizer、ActionRouterV3、OutputGuard、Pipeline 及所有 frozen evidence。
- **放入 V4**：非空形近映射、预训练模型适配器，以及任何会改变检测证据分布或动作行为的增强。

---

审计期间未运行 internal holdout，未查看 holdout 原文或逐条预测，未修改任何 frozen 文件。
