# SafeChat-Guard 当前项目状态

> 审计日期：2026-07-13  
> 结论来源：仓库、Git、代码、配置、数据、测试、文档及隔离运行验证。  
> 状态标记：**已验证**表示有源码、Git、数据统计或运行结果支持；**合理推断**表示由现有证据推导；**无法确认**表示仓库内证据不足。

## 1. 执行摘要

SafeChat-Guard 已形成可运行的比赛原型：输入归一化、规则检测、风险分级、Mock 模型调用、输出复检、日志统计、基础网页和 Streamlit 展示均已接通。隔离环境验证中，44 个 Python 文件语法检查通过，现有 41 项 pytest 全部通过，HTTP 与 Streamlit 前端均能启动。

但核心安全效果尚未达到可靠交付标准：内置 32 条业务样例仅 14 条动作正确，应拦截的 13 条样例仅拦截 2 条；真实语义模型、真实下游模型、完整安全改写和正式 gold 评估集均缺失。当前具备比赛 Demo 骨架，但在修复高风险漏检和语义脱敏漏洞前，不具备可靠比赛演示或 SIT 实验结论基础。

## 2. 仓库与 Git 状态

- 仓库根目录：`D:\Projects\SafeChat-Guard`
- 当前分支：`feat/data-baseline-v1`
- 当前提交：`72b39df`
- 当前分支、`main` 和 `origin/main` 指向同一提交。
- 审计时没有已修改或已暂存的跟踪文件，stash 为空。
- 存在尚未提交的数据基线工作：`data/evaluation/`、`reports/`、数据文档、6 个数据脚本和 3 个测试文件。
- `fix/pipeline-semantic-integration` 与 `backup-main-before-sync-20260711` 保留了平行恢复历史，后续合并时需避免把旧版本重新覆盖到当前实现。
- `.gitignore` 已忽略密钥、模型、训练 CSV、运行日志、虚拟环境和 Python 缓存；未发现已提交的模型权重、密钥或运行日志。
- 模型和训练 CSV 被忽略后，没有配套的制品下载地址、版本登记或 checksum，干净环境无法复现语义模型。

## 3. 当前真实架构与流程

```text
app.py 或 frontend/streamlit_app.py
  → FrontendPipelineAdapter（Streamlit 路径）
  → SafeChatPipeline
      → TextNormalizer
          → Unicode / Case
          → Emoji / Variant / Homophone
          → Pinyin / Abbreviation
          → Noise / Repeat
      → RuleFilter
      → SemanticClassifier（当前模型未加载）
      → 风险阈值决策
          → block / sanitize / pass
      → MockLLMClient
      → OutputGuard
      → EventLogger
```

真实调用链如下：

```text
用户输入
→ 中文归一化
→ 关键词与正则检测
→ 可选语义检测（当前返回空结果）
→ 取所有 Detection 的最高分
→ score ≥ 80：直接拦截
→ 40 ≤ score < 80：字符串遮罩
→ score < 40：正常放行
→ Mock 模型返回回复
→ 输出再次归一化和检测
→ 输出隐私规则及额外高风险规则
→ 拦截、替换或放行
→ 写入 JSONL 日志并返回结果
```

当前项目更接近“带两个前端的实验型比赛原型”，还不是可安装、可部署、可完整复现实验的产品。

## 4. 模块进度矩阵

| 模块 | 当前状态 | 已实现 | 主要缺口 | 主流程接入 | 完成度判断 |
| --- | --- | --- | --- | --- | --- |
| 中文归一化 | 模块化可用 | facade、pipeline、trace、Unicode、大小写、映射、噪声和重复字符处理 | 无配置开关和例外表；部分扰动类型恢复率为 0 | 是 | 基本完成 |
| 规则过滤 | 可运行 | 四类词库、7 条正则、真实命中证据 | 正则全部归入 `ad`；上下文能力弱；实际召回低 | 是 | 部分完成 |
| 语义分类 | 接口已接入 | joblib 加载、概率转 Detection、状态接口 | 模型文件不存在；无真实推理、校准和批处理证据 | 是，但实际空跑 | 部分完成 |
| 风险决策 | 可运行 | 合并规则和语义结果，按最高分决策 | 未按类别和来源制定策略；存在语义 sanitize 漏洞 | 是 | 部分完成 |
| 脱敏 | 简单可用 | 按真实规则命中值替换为 `***` | 语义命中不能定位原文；无重检 | 是 | 部分完成 |
| 安全改写 | 未实现 | 输出侧有固定拒答和标签替换 | 无 `SafeRewriter`、语义保持、情感保持和失败回退 | 否 | 未开始 |
| 下游模型 | Mock | 统一 `chat()` 接口 | provider、key、URL 和 model 配置均未使用 | 是，Mock | 原型阶段 |
| 输出复检 | 可运行 | 规则复用、隐私正则、额外高风险短语、固定拒答 | 语义 sanitize 可原样返回 | 是 | 基本完成 |
| 日志统计 | 可运行 | JSONL、类别/等级/动作统计 | 明文日志、无轮转、无延迟和误判字段 | 是 | 基本完成 |
| 后端 | 可启动 | 主页、`/api/chat`、`/api/stats` | 无健康接口、请求 schema、大小限制和统一异常处理 | 是 | 基本完成 |
| 前端 | 两套可运行 | 基础网页与多页 Streamlit 控制台 | 指标主要依赖 12 条样例；状态文案有夸大 | 是 | 基本完成 |
| 数据生成 | 新旧流程并存 | V1/V2 评估候选、对抗扰动、稳定 ID | 无正式训练文件，训练和数据基线流程未统一 | 独立脚本 | 部分完成 |
| 数据审核 | 有框架 | 重复、冲突、非法、泄漏候选和审核状态 | 正式集均为 pending；复核优先队列脚本未完成 | 否 | 部分完成 |
| 自动评估 | 演示级 | 12 条前端批处理、混淆矩阵、误判率 | 无正式 gold CLI evaluator 和科研指标 | 部分 | 原型阶段 |
| 工程测试 | 较好 | 41 项 pytest；44 个 Python 文件语法通过 | 业务样例未纳入 pytest；无 CI、lint 和类型检查 | — | 基本完成 |
| 文档与展示 | 有基础 | 中文 README、架构、启动、数据规范和报告页 | 英文 README 是模板；接口名过时；无真实实验报告 | — | 部分完成 |

## 5. 已验证成果

1. 模块化归一化 facade、pipeline 和 trace 已接入主流程，归一化测试通过。
2. 输入和输出均联合执行规则检测与可选语义检测，不再用其中一层覆盖另一层。
3. 高分输入命中时会跳过下游模型并直接返回拦截结果。
4. 输出侧实现了手机号、邮箱、身份证、银行卡、URL、IP、微信号、QQ 和地址等隐私检查。
5. 基础 HTTP 页面、`/api/chat`、`/api/stats` 和 Streamlit 控制台均可启动。
6. JSONL 日志与统计闭环可运行；现有日志 407 行，全部为合法 JSON。
7. 数据基线脚本已实现稳定 ID、UTF-8、冲突队列、泄漏候选和对抗生成短缺报告。
8. 隔离副本中 44 个 Python 文件无语法错误，pytest 结果为 `41 passed`。

## 6. 关键未完成与伪完成

1. **测试通过不等于安全效果通过。** `data/test_cases/sample_cases.jsonl` 的 32 条业务样例未被纳入 pytest；实际仅 14/32 动作正确。
2. **语义分类器已接入但未启用。** 当前状态为 `loaded=false`，错误为 `model file not found`；相关测试使用 Fake 模型验证接口。
3. **脱敏/改写主要是字符串替换。** 当前没有完整的 `SafeRewriter`。
4. **下游模型是假接入。** 任意 provider 最终都会返回 Mock 客户端。
5. **语义 sanitize 可能完全不改变文本。** 语义 Detection 的 `matches` 是“类别: 概率”说明，不是原文 span；输入可显示 `sanitize` 但原样转发，输出可显示 `rewritten=true` 但原样返回。
6. **V2 已复核文件没有实际复核。** `adversarial_sample_v2_reviewed_oxygen.csv` 与原抽样文件字节完全一致，33 条仍全部为 pending。
7. **复核优先队列脚本未完成。** `scripts/build_review_priority_queue.py` 只有辅助函数，没有构建流程、CLI 或 `main()`。
8. **新数据链未连接训练脚本。** `train_classifier.py` 仍读取旧的 `raw_train_v3.csv`，不读取 clean/candidate 数据。
9. **文档与实现不一致。** 前端文档引用不存在的 `filter_input()`/`filter_output()`；Streamlit 将未加载的语义模型标记为真实模块；英文 README 仍是模板。
10. **旧版与新版流程并存。** deprecated、V3 和新数据基线脚本尚未形成唯一权威入口。

## 7. 数据现状

### 7.1 源数据规模

| 数据 | 行数 | 质量情况 |
| --- | ---: | --- |
| 正常句子 | 189 | 138 唯一，51 条重复 |
| 广告违规句子 | 75 | 75 唯一 |
| 色情违规句子 | 74 | 74 唯一 |
| 敏感违规句子 | 82 | 82 唯一 |
| 暴力违规句子 | 66 | 66 唯一 |
| 广告词库 | 66 | 无文件内重复 |
| 色情词库 | 323 | 无文件内重复 |
| 敏感词库 | 799 | 无文件内重复 |
| 暴力词库 | 610 | 无文件内重复 |
| JSONL 开发样例 | 32 | pass 6 / sanitize 13 / block 13 |
| 前端样例 | 12 | pass 6 / sanitize 5 / block 1 |

归一化映射规模：abbreviation 20、emoji 63、homophone 29、pinyin 19、variant 21。全部 JSON 可解析，但有 4 个 emoji 在完整流水线中的结果与映射目标不等价。

### 7.2 评估候选和审核状态

| 文件 | 规模 | 分布 | 审核状态 |
| --- | ---: | --- | --- |
| baseline V1 | 200 | normal 80，其余每类 30 | 全部 pending |
| adversarial V1 | 130 | ad 109、porn 21 | 全部 pending |
| adversarial V2 | 97 | ad 30、porn 33、sensitive 14、violence 20 | 全部 pending |
| baseline 人工抽样 | 50 | 每类 10 | verified 26、pending 24 |
| adversarial V1 人工抽样 | 39 | ad 35、porn 4 | verified 20、rejected 10、pending 9 |
| adversarial V2 抽样 | 33 | 多类 | 全部 pending |

V2 对抗生成短缺 33 条，其中 phone/url obfuscation 均未生成。V1 有 153 组、V2 有 74 组归一化近似重复候选，必须人工判断，不能直接视为独立测试样本。

`pair_id` 一致性检查通过：V1 的 130 个 sample_id 和 V2 的 97 个 sample_id 均唯一；同一 pair_id 始终映射到相同原文、标签和来源。pair_id 重复表示同一原文生成多个扰动，不是字段错误。

### 7.3 当前运行效果

| 评估 | 结果 |
| --- | ---: |
| 内置 32 条样例动作准确率 | 14/32 = 43.75% |
| 应 block 的 13 条样例实际 block | 2/13 = 15.38% |
| 前端 12 条输入动作准确率 | 8/12 = 66.67% |
| baseline pending 正常误报 | 2/80 = 2.5% |
| baseline pending 风险样本得到处理 | 24/120 = 20% |
| verified baseline 风险子集得到处理 | 5/17 = 29.41% |
| verified adversarial V1 得到处理 | 6/20 = 30% |
| adversarial V2 pending 得到处理 | 27/97 = 27.84% |
| 归一化恢复 V1 | 73/130 = 56.15% |
| 归一化恢复 V2 | 69/97 = 71.13% |
| 无模型状态下单次输入过滤平均耗时 | 约 0.25–0.60 ms |

pending 数据只能用于诊断，不能作为正式比赛或论文成绩。当前没有真实训练 CSV；旧训练流程会先复制过采样再按行随机拆分，可能让相同文本副本同时进入训练和测试，造成指标虚高。

## 8. 主要风险

### P0：必须立即处理

#### P0-1 高风险召回严重不足

- 证据：内置 13 条应 block 样例仅 block 2 条；verified adversarial 仅识别 6/20。
- 影响：直接违反“高风险必须阻断”的设计约束，比赛现场可能出现严重安全失败。
- 建议：立即将业务样例和 verified 子集加入 pytest，针对漏检补规则、映射和类别策略。

#### P0-2 语义 sanitize 可原文不变

- 证据：隔离反例中输入 `action=sanitize` 但处理后文本不变；输出 `rewritten=true` 但最终文本与原文一致。
- 影响：启用真实语义模型后，风险内容可能原样进入下游或返回用户。
- 建议：语义检测无法提供 span 时禁止使用字符串遮罩；高危类别直接 block，中风险走受控改写并强制复检。

### P1：核心交付风险

1. 真实语义模型和真实下游模型均缺失。
2. 完整安全改写与改写后重检尚未实现。
3. 旧训练流程存在重复样本跨训练/测试泄漏风险。
4. 三个正式 evaluation CSV 全部 pending，尚未形成冻结 gold 集。
5. 日志明文保存输入、输出和潜在隐私，且没有轮转和保留期。
6. 数据基线成果尚未提交，复核优先队列脚本不完整。

### P2：工程与演示风险

1. HTTP JSON 数组请求会触发未捕获 `AttributeError` 并断开连接。
2. 缺少 `/health`、请求长度限制、统一错误响应和 CORS 配置。
3. 没有 CI、lint、类型检查和包安装配置。
4. 页面和文档对 Mock、pending、未加载语义模型的状态说明不够准确。
5. 日志缺少并发保护、延迟和误判统计。

### P3：后续优化

mixed language、电话、URL、重复字符和繁简扰动的归一化恢复仍明显不足；应先根据 verified 失败样本补规则、例外和回归测试，不宜短期引入复杂外部 NLP 服务。

## 9. 辅助完成度判断

百分比基于“实现、接入、测试、运行证据、效果和数据质量”加权，仅用于项目管理，不代表正式成绩。

| 维度 | 状态 | 辅助评分 | 判断依据 |
| --- | --- | ---: | --- |
| 比赛作品工程 | 原型阶段 | 52% | 闭环和 UI 可运行，但真实模型、可靠效果和正式指标缺失 |
| 核心安全流程 | 部分完成 | 45% | 流程接通，但高风险召回和语义 sanitize 存在 P0 |
| 中文归一化 | 基本完成 | 71% | facade、trace 和测试较好；多个扰动类型仍无法恢复 |
| 数据与评测 | 部分完成 | 50% | schema 和脚本较完整；gold、训练集和一键指标不足 |
| SIT 科研准备 | 原型阶段 | 30% | 有方向和候选数据，无可信训练、实验和模型结果 |
| 文档与答辩材料 | 部分完成 | 52% | 中文文档和展示存在，实验结果与一致性不足 |

综合判断：

- 已具备比赛 Demo 的工程骨架。
- 尚不具备可靠安全演示条件，必须先修复 P0。
- 仅形成早期 SIT 数据工程基础，不能声称已形成科研实验闭环。
- 不能声称真实语义分类、真实 LLM 或完整安全改写已经完成。

## 10. 下一阶段计划

### 接下来 3 天

1. 将 `sample_cases.jsonl` 和 verified 子集接入 pytest。
2. 增加安全不变量：高风险不得 pass；sanitize 必须改变文本，否则 block。
3. 修复语义命中无法定位原文时的决策与回退逻辑。
4. 根据 verified 漏检补充词库、正则和归一化映射。
5. 审核并提交当前未跟踪的数据脚本、报告、测试和文档；完成或移除残缺入口。

验收标准：高风险回归用例不再 pass；verified baseline 风险处理率先达到 80% 以上，正常误报控制在 5% 以下。

### 接下来 1 周

1. 建立至少 100 条基线、80 条对抗样本的冻结 verified gold 集。
2. 实现一键评估脚本，输出 recall、FPR、macro F1、对抗恢复率和延迟。
3. 使用按原始样本分组拆分的 clean 数据训练轻量 TF-IDF/LogReg 基线。
4. 实现一个 OpenAI-compatible 或 Qwen 下游客户端，并保留无 key 的 Mock 降级。
5. 加入请求 schema、长度限制、健康接口、日志脱敏和统一错误处理。

### 接下来 2 周

1. 实现受控安全改写和改写后重检，失败时回退到 block。
2. 页面动态展示真实模型状态和正式评估指标，不再将 Mock/pending 写成已完成。
3. 形成答辩演示脚本、截图、混淆矩阵、误差分析和正式技术报告。
4. 在干净环境执行安装、测试、启动和完整 Demo 彩排。

### 延后到 SIT 阶段

- XLM-R/RoBERTa 跨语言迁移；
- 大规模生成式去毒与 ParaDetox 类方案；
- 多轮上下文、隐喻、反讽和价值观评估；
- 完整数据卡、消融实验、统计显著性和人工一致性研究。

## 11. 建议团队分工与接口

| 成员 | 主责 | 交付物 |
| --- | --- | --- |
| A | 数据与归一化 | 版本化 CSV、标注记录、映射、归一化恢复报告、失败样本清单 |
| B | 语义模型与风险决策 | 模型及 checksum、训练配置、指标 JSON、阈值和 Detection 输出 |
| C | 后端与系统集成 | API、LLM 适配、输出复检、异常策略和脱敏日志 |
| D | 独立评估、前端和展示 | 一键评估器、混淆矩阵、延迟报告、Demo 脚本和截图 |

建议冻结以下接口和行为：

1. `Detection(category, level, score, reason, source, matches)`。
2. `action` 只允许 `pass`、`sanitize`、`block`。
3. `NormalizationResult(original_text, normalized_text, steps)`。
4. 输入和输出过滤结果必须保留原文、归一化文本、动作、分数、detections 和处理后文本。
5. 评估数据必须保留 `sample_id`；对抗数据同时保留 `pair_id`、原文、扰动文本和扰动类型。
6. 任何 sanitize/rewrite 必须满足：结果非空、确实改变、复检通过，否则 block。
7. A 不直接调整 B 的阈值；B 不直接修改 gold 标签；D 使用冻结 gold 独立评估；C 只消费约定接口。

## 12. 待团队确认

1. 比赛截止日期、评分细则，以及是否必须调用真实大模型。
2. 允许使用的 LLM 服务、API 预算、现场网络条件和密钥管理方式。
3. 最终标签是否只保留五类；当前前端、输入侧和输出侧标签体系不完全一致。
4. 哪些类别必须无条件 block，哪些允许 sanitize/rewrite。
5. verified 是否要求双人独立复核及一致性记录，谁拥有最终审批权。
6. 模型制品通过 Git LFS、Release、网盘还是现场训练提供。
7. 比赛部署硬件、操作系统、Python 版本和可安装依赖范围。
8. SIT 最终研究问题、目标成果形式以及是否涉及真实用户数据和伦理要求。

## 13. 常用命令与注意事项

```powershell
python app.py
python -m streamlit run frontend/streamlit_app.py
python -m pytest -q
python scripts/build_evaluation_sets.py
python scripts/build_evaluation_sets.py --mode adversarial-v2
```

注意：当前 pytest 中部分管线测试会向 `config.yaml` 指定的 `data/logs/events.jsonl` 追加记录。需要严格只读验证时，应在临时副本中运行测试。

## 14. 不应随意改变的约束

- 高风险内容必须直接 block，不能用改写替代阻断。
- LLM 不能作为唯一安全保障。
- 中风险内容只有在处理结果确实改变且复检安全时才能转发。
- 自动生成数据默认是 pending，只有 verified 才能进入正式评估。
- 规则和语义结果都必须保留，不能相互短路覆盖。
- 不应随意改变 `Detection` 字段、动作集合、`TextNormalizer` 兼容入口、`sample_id`/`pair_id` 语义和评估 CSV schema。

