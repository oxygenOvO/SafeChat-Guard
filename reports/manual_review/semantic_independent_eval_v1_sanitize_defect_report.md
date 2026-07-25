# 独立人工评估集 V1 sanitize 候选缺陷报告

## 0. 当前归档结论

本报告保留 sanitize 候选缺陷发现、修复和分阶段试审过程，当前归档结论以 `semantic_independent_eval_v1_final_review_completed.csv` 为准：

- 最终审核表共 200 条，200 个 `sample_id` 唯一；
- 200 条均为 `verified`，`pending` 和 `rejected` 均为 0；
- 最终 40 条 `expected_action=sanitize` 样本均为 `verified`，其中 ad、porn、violence、sensitive 各 10 条；
- 最终表全部由 `reviewer_1` 完成，属于单人独立审核结果，不是双人复核 Gold；
- 历史章节中的 `pending`、`rejected` 和试审门禁结论只描述当时阶段，不代表最终审核表的当前状态；
- 本成果不得用于训练，只用于独立评估和错误分析。
## 1. 审核范围与统计

本报告记录 A 组独立人工评估集 V1 的 sanitize 专项人工审核结果。专项表覆盖原始候选中全部 40 条 `expected_action=sanitize` 样本。

| label | 审核数 | verified | rejected | pending | 通过率 |
|---|---:|---:|---:|---:|---:|
| ad | 10 | 1 | 9 | 0 | 10.0% |
| porn | 10 | 0 | 10 | 0 | 0.0% |
| violence | 10 | 0 | 10 | 0 | 0.0% |
| sensitive | 10 | 0 | 10 | 0 | 0.0% |
| **合计** | **40** | **1** | **39** | **0** | **2.5%** |

除 sanitize 专项外，30 条试审还确认 `siev1_238ce08ce94faede` 为 rejected。该样本的核心危害是私密影像勒索与隐私侵害，不适合作为 porn/block Gold 样本。

## 2. 系统性缺陷

原始 sanitize 候选普遍把“审核、脱敏、编辑或安全处置风险内容的说明”误当成“文本本身包含需要 sanitize 的风险内容”。

多数失败样本只声称另一段材料存在号码、账号、露骨台词、暴力细节、住址或病历字段，但候选文本中并未真实呈现这些内容。因此：

- 无法定位实际风险片段；
- 无法验证删除、替换或安全改写是否有效；
- 文本的真实言语行为通常是治理、教育、举报、劝阻或安全处置；
- 原始风险 label 与 `sanitize` 动作同时失去依据。

## 3. 典型失败模式

1. **处置说明代替原始风险载荷**：只写“应遮盖号码”“应删除账号”，却没有号码或账号。
2. **风险词引用被误判为风险行为**：教学、研究、新闻、举报和审核语境中的引用被直接赋予风险标签。
3. **虚构或比喻语境被误判**：游戏、小说、比赛评论中的概括性表达被标为 violence/sanitize。
4. **合法求助或健康语境被误判**：求助、康复、医学访谈本身没有自伤方法、鼓励或真实身份字段。
5. **标签按局部关键词生成**：没有按文本主要危害和实际言语行为确定 label。
6. **动作不可验证**：删除所谓风险内容后是否存在完整、合法主体无法从文本中判断。
7. **多风险主标签错误**：私密影像勒索样本按 porn 标注，忽略了隐私侵害与胁迫这一主要危害。

## 4. 对 Gold 有效性的影响

如果直接将原始候选按现有 label/action 纳入 Gold，会系统性高估风险类别和 sanitize 路由，造成：

- normal/pass 样本被错误计为风险样本；
- sanitize 指标衡量的是模板词，而不是真实可改写风险；
- 模型可能学习“遮盖、删除、脱敏”等处置词与风险标签之间的伪相关；
- porn、violence、sensitive 的类别边界被治理语境和关键词引用污染；
- 后续系统对教育、新闻、求助和安全处置文本产生不必要误报。

因此，39 条 rejected sanitize 候选和 1 条标签错误的 porn/block 候选不得进入当前 Gold。

## 5. 修复目标

保留原始 200 条候选作为不可变审计基线，另外生成修复版候选：

- 原样保留其余 160 条；
- 替换 9 条 ad/sanitize；
- 替换 10 条 porn/sanitize；
- 替换 10 条 violence/sanitize；
- 替换 10 条 sensitive/sanitize；
- 替换 1 条 porn/block；
- 使用稳定 SHA-256 sample_id；
- 通过 manifest 记录每一条 old/new 映射；
- 在该历史生成阶段，新样本全部为 pending，reviewer 为空；这些样本后续已经完成人工审核，最终状态以归档主表为准；
- 修复版仍保持 200 条及原有 label/action 分布。

## 6. 验收门槛

新 sanitize 候选必须同时满足：

1. 风险片段真实出现在候选文本中；
2. 风险片段可准确定位；
3. 删除或安全改写后仍保留合法、完整、有意义的主体内容；
4. 核心目的不是严重违法、交易、伤害、胁迫或鼓励；
5. label 与主要危害一致；
6. 不包含真实个人信息、真实账号、真实联系方式或可执行犯罪细节；
7. 不以“某内容含有风险，请删除/遮盖/脱敏”为主要句式；
8. 避免批量复用单一模板。

porn/block 替换样本必须以色情内容传播或交易为主要危害，不能以隐私勒索等其他危害为核心。

数据层验收门槛：

- 修复版共 200 条且 sample_id 唯一；
- label/action 分布与原始目标完全一致；
- 精确、NFKC、TextNormalizer 等价重叠均为 0；
- 标签冲突和重复 sample_id 均为 0；
- 与训练源、旧评估集及被淘汰文本不存在硬重叠；
- 字符 3-gram 高相似项进入报告并保留人工复核证据；
- 重复运行生成文件字节级一致；
- 审计未通过时不得生成修复版审核模板。

## 7. 原始 V1 保留原则

以下原始 V1 文件必须保持不变，作为候选生成、试审、专项审核和规则冻结的完整证据：

- `data/evaluation/semantic_independent_eval_v1_candidates.csv`
- `reports/manual_review/semantic_independent_eval_v1_review_template.csv`
- `reports/manual_review/semantic_independent_eval_v1_trial30.csv`
- `reports/manual_review/semantic_independent_eval_v1_sanitize_audit.csv`
- `reports/manual_review/semantic_independent_eval_v1_review_rules_v1.md`

修复版使用独立文件名和独立审计目录，不覆盖、不回写原始 V1，也不在本阶段生成 Gold。
## 第二轮修复试审

修复候选固定分层二次试审共13条，其中12条为sanitize、1条为porn/block。

- 旧的“把处置说明当成待处置文本”的元说明缺陷基本消失，12条sanitize均出现了可定位风险片段。
- sanitize试审结果为9条verified、3条rejected，通过率为9/12（75.0%），未达到10/12门禁。
- ad、porn、sensitive各出现1条失败；violence的3条sanitize均通过。
- 新发现“合法主体＋风险尾句”的固定二段式模板，部分样本存在拼音规避不自然、整体语义仍属合法引用或上下文机械拼接问题。
- 当前修复版不得进入完整审核；应先修订或替换3条失败样本并重新通过门禁。
## Repair V2候选重建

- 历史试审证据 `semantic_independent_eval_v1_repair_trial13_v1.csv` 及其 10 verified / 3 rejected 结论保持不变。
- Repair V2针对整批39条sanitize替换候选重新生成，而不是只修补3条试审失败样本；分布仍为ad 9条、porn 10条、violence 10条、sensitive 10条。
- Repair V1中已通过试审的porn/block替换候选保持原sample_id、文本和映射不变。
- 新增结构元数据与自动门禁，检查结构类型、风险位置、sanitize操作、元说明、固定二段式、模板签名、非自然规避及已知机械拼接。
- Repair V2候选的自动独立性审计和结构审计均已通过；在该历史阶段，39条新候选全部为pending且reviewer为空，后续状态已在最终审核表中闭环。
- 该历史阶段仅完成候选重建和自动审计，当时尚未产生新的人工审核结论，也未构建Gold；后续固定分层试审和完整200条审核现已完成。

## Repair V2人工试审

Repair V2固定分层人工试审共12条，结果为10条verified、2条rejected、0条pending，数量门槛达到10/12。

- 旧的“把处置说明当成待处置文本”的元说明缺陷为0。
- 标签错误、风险片段缺失和安全引用误标均为0。
- 仍发现2条跨类别无关场景拼接，分别涉及porn与sensitive候选，说明“合法主体＋无关风险片段”的语义关联缺陷尚未完全消除。
- Repair V2在该历史阶段暂不进入完整审核，也不构建Gold；后续修复和完整审核现已完成。
- 下一阶段采用V2.1语义关联专项修复，重点验证合法主体与风险片段之间是否存在自然、必要且可解释的场景联系。

## Repair V2.2 定向修复

Repair V2.1 的39条 sanitize 人工审核主表已冻结为35条 verified、4条 rejected、0条 pending。本轮仅替换这4条人工拒绝候选，其余35条已验证候选的 sample_id 与文本保持不变。

- violence/sanitize：将缺少自然施威者的借书提醒替换为团队协作中的页面修改冲突。
- sensitive/sanitize：将3条与普通活动或出行安排机械拼接的健康信息，分别替换为住宿照护、学校健康保障和健康互助登记场景。
- 4条新候选的 generation_version 均为 independent_eval_v1_repair_v2_2；在该历史生成阶段审核状态为 pending、reviewer 为空，后续均已完成人工审核。
- 4条新候选与训练源、旧评估集、原始淘汰文本、Repair V1及Repair V2.1历史文本的精确、NFKC和TextNormalizer等价重叠均为0；字符3-gram高相似、内部高相似、标签冲突和重复sample_id均为0。
- 结构多样性、风险片段可定位、sanitize后主体有效、语义关联和真实个人标识门禁均通过。
- 35条已verified候选的保护哈希前后均为 c28174e6127a4ba6736391c82e7b2e626018ed6951524d9e04a8fbb963c86824。
- 该历史轮次只完成候选定向修复与自动审计，当时未写入人工审核状态，也未生成Gold；4条新候选的人工复验和最终200条审核现已完成。
