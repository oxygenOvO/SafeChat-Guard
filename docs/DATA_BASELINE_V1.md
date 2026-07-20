# SafeChat-Guard 数据基线 V1

## 数据源清单

| 路径 | 格式 | 用途 | 是否直接作为正式评估 |
| --- | --- | --- | --- |
| `data/normal_sentences.txt` | 每行一句 | 正常类候选来源 | 否，构建后为 pending |
| `data/violation_sentences/*.txt` | 每行一句 | 四类风险候选来源 | 否，构建后为 pending |
| `data/test_cases/sample_cases.jsonl` | JSONL | 现有开发测试与泄漏参照 | 否 |
| `data/test_cases/frontend_cases.csv` | CSV | 前端开发测试与泄漏参照 | 否 |
| `data/lexicons/*.txt` | 每行一词 | 规则词库，不是句子级 gold 数据 | 否 |
| `data/maps/*.json` | JSON 映射 | 对抗候选生成规则 | 否 |

当前工程保留 `data/training_data/raw_train.csv` 和 `raw_train_v3.csv` 作为已有训练
候选源；清洗后的派生 CSV 由 `.gitignore` 排除，需通过脚本复现。运行日志不得作为
训练来源，新增数据必须记录来源、版本并通过审计后使用。

## 字段与合法标签

训练清洗输出字段：`sample_id,text,label,source,data_version`。

基线评估字段：
`sample_id,text,label,scenario,source,review_status,notes`。

对抗评估字段：
`sample_id,pair_id,original_text,adversarial_text,label,perturbation_type,source,review_status,notes`。

合法标签与当前分类器一致：`normal`、`ad`、`porn`、`violence`、`sensitive`。

复核状态：

- `verified`：人工确认，可进入正式评估；
- `pending`：自动生成、自动筛选或尚未人工确认；
- `rejected`：人工复核后不使用。

## 审计与清洗

```bash
python scripts/audit_training_data.py --input data/training_data/raw_train_v3.csv --report-dir reports/data_audit_v1
python scripts/build_clean_dataset.py --input data/training_data/raw_train_v3.csv --output data/training_data/train_clean_v1.csv --review-output reports/data_audit_v1/manual_review_queue.csv
```

审计报告包括 JSON/Markdown 摘要、重复、冲突、非法行和泄漏候选 CSV。
清洗不会调用 Normalizer 改写训练文本，不基于关键词改标签。冲突标签全部进入人工队列。

`sample_id` 是 `text + label + source` 的 SHA-256 截断值；相同输入得到相同 ID。
数据版本使用语义名称，例如 `train_clean_v1`，规则变化后递增版本，不覆盖旧版本。

## 评估与对抗集构建

```bash
python scripts/build_evaluation_sets.py --output-dir data/evaluation --report-dir reports/data_audit_v1
```

如训练 CSV 存在，增加：

```bash
python scripts/build_evaluation_sets.py --train-input data/training_data/train_clean_v1.csv --output-dir data/evaluation --report-dir reports/data_audit_v1
```

脚本生成 `baseline_eval_v1.csv`、`adversarial_eval_v1.csv`、覆盖统计和泄漏候选。
所有自动构建样本均为 `pending`。对抗集保留原文、扰动文本、稳定 `pair_id` 和生成规则。
同时生成 `evaluation_duplicate_candidates.csv`，记录评估候选内部的文本哈希与
归一化近似重复，供人工排除非独立样本。

严格对抗候选版本使用：

```bash
python scripts/build_evaluation_sets.py --mode adversarial-v2
python scripts/build_evaluation_sets.py --mode adversarial-v3
```

V3 不覆盖 V2，并生成独立的覆盖、重复、失败和 V2→V3 差异报告。
所有 V3 自动候选重新置为 `pending`，不继承 V2 人工状态。`variant_character`
只接受显式维护的等长中文形近字或异体字替换；符号插入归
`symbol_insertion`，繁简转换归 `traditional_simplified`。

`homophone` 映射按 `high`、`medium`、`low` 分级：high 可自动生成，medium
进入高优先级定向复核，low 默认排除。普通风险词内部空格插入统一归
`space_insertion`；`character_split` 暂停，直至存在人工确认的中文偏旁拆字
映射。不得把旧 character_split 样本改名后重复写入新版本。

`repeat_character` 属于合成压力样本，可用于测试鲁棒性，但正式报告必须作为
`synthetic stress test` 单独统计。真实攻击样本与合成压力样本不得混合解释为
同一种自然分布。

## 数据泄漏规则

训练集与测试/评估集依次检查：完全相同、首尾空格归一、大小写归一、Unicode
NFKC 归一和项目 Normalizer 归一后的相同文本。命中只写入候选报告，不自动删除。

## 人工复核流程

1. A 组检查 `manual_review_queue.csv` 的冲突标签，不自动多数投票。
2. 两名复核人员独立检查 `pending` 的语义、类别、场景和扰动保真度。
3. 一致通过后改为 `verified`；不确定项保留 `pending`；错误项标记 `rejected`。
4. 正式测试只读取 `verified`，并保存复核记录和数据版本。
5. 每次训练前重新运行泄漏检查，人工处理候选匹配。

## A 组交付 B 组

B 组训练时使用 `train_clean_v1.csv` 的 `text` 与 `label`，保留 `sample_id` 便于追踪。
模型选择和调参不得读取正式评估标签。完成训练后由 A 组使用 `verified` 评估集独立评测。
对抗集应按 `pair_id` 对比原文与扰动文本表现。

## 已知局限

- 当前训练 CSV 属于已有候选数据，来源独立性和人工标注质量仍需继续核验；
- 候选评估数据来自仓库现有句子文件，尚未完成独立人工复核；
- 自动扰动可能改变语气或语义，必须保持 `pending` 直至人工确认；
- 基础字符串匹配不能识别所有语义近似泄漏；
- 文档不记录未经实际运行验证的样本数量或模型指标。
