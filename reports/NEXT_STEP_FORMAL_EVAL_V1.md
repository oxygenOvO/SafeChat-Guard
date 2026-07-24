# SafeChat-Guard 独立评估 V1：下一步执行说明

## 当前状态

- 审核候选：200 条，`verified=200`、`pending=0`、`rejected=0`。
- 第一审核者：全部为 `reviewer_1`。
- 数据质检：sample_id 唯一且可复现；无精确重复文本；无归一化重复组；字段完整。
- 当前产物应称为 **单审版 Gold V1（provisional single-review Gold）**，不建议在第二审核前表述为“双审高可信金标”。
- 当前数据为人工单审结论，AI仅辅助候选整理和工作流执行，第二位独立审核者复核仍待完成。

## 已生成的文件

1. `semantic_independent_eval_v1_final_review_completed.csv`：第一审核者完整审核表。
2. `semantic_gold_v1_single_review.csv`：与仓库 `build_semantic_gold_v1.py` 结构兼容的 Gold；校准集 80 条、测试集 120 条。
3. `semantic_independent_eval_v1_second_review_blind.csv`：40 条分层盲审样本；已清空第一审核者结论与说明。
4. `compare_second_review_v1.py`：第二审核完成后生成一致率和分歧表。
5. `run_formal_eval_v1.ps1`：构建 Gold、运行测试并执行三种模式评估。
6. `semantic_gold_v1_manifest.json`：数据分布、哈希、质检结果和限制说明。

## 第二审核流程

第二审核者只修改盲审表中的：

- `review_status`：`verified / rejected / pending`
- `reviewer`：填写 `reviewer_2`
- `notes`：说明判断理由

不要修改 `text、label、risk_level、expected_action、scenario、source_type、source_reference`。

完成后运行：

```powershell
python compare_second_review_v1.py `
  --first-review semantic_independent_eval_v1_final_review_completed.csv `
  --second-review semantic_independent_eval_v1_second_review_blind.csv
```

处理原则：

- 所有分歧必须逐条裁决；
- 若分歧集中在同一类别或动作，应扩审该分层，而不是只改分歧行；
- 裁决完成后再冻结正式 Gold。

## 仓库落位建议

```text
reports/manual_review/semantic_independent_eval_v1_final_review_completed.csv
reports/manual_review/semantic_independent_eval_v1_second_review_blind.csv
data/evaluation/semantic_gold_v1.csv
scripts/compare_second_review_v1.py
scripts/run_formal_eval_v1.ps1
```

`semantic_gold_v1_single_review.csv` 放入仓库时可重命名为：

```text
data/evaluation/semantic_gold_v1.csv
```

## 正式评估顺序

1. 只在 `calibration` 的 80 条上检查误报、漏报并校准配置。
2. 比较 `rule_only / semantic_only / combined`。
3. 冻结模型文件、规则词库、阈值、依赖版本和提交 SHA。
4. 再对 `test` 的 120 条运行一次最终评估。
5. 测试集结果只能用于报告，不得据此继续调参。

在仓库根目录运行校准评估：

```powershell
.\run_formal_eval_v1.ps1 `
  -ProjectRoot "D:\Projects\SafeChat-Guard" `
  -ReviewCsv "D:\Projects\SafeChat-Guard\reports\manual_review\semantic_independent_eval_v1_final_review_completed.csv" `
  -EvaluationSplit calibration
```

配置冻结后运行最终测试：

```powershell
.\run_formal_eval_v1.ps1 `
  -ProjectRoot "D:\Projects\SafeChat-Guard" `
  -ReviewCsv "D:\Projects\SafeChat-Guard\reports\manual_review\semantic_independent_eval_v1_final_review_completed.csv" `
  -EvaluationSplit test
```

## 最终需要报告的指标

- Accuracy、Macro Precision、Macro Recall、Macro F1；
- normal 误报率；
- high-risk block recall；
- sanitize routing recall；
- action accuracy；
- 各类别 Precision / Recall / F1；
- 混淆矩阵；
- `rule_only / semantic_only / combined` 对比；
- 模型是否正常加载、模型文件哈希、代码提交 SHA。

## 禁止事项

- 不得将 Gold 的 calibration 或 test 样本加入训练数据；
- 不得在查看 test 结果后继续改阈值或规则；
- 不得把 pytest 通过数量当作检测效果；
- 第二审核完成前，不把当前版本表述为“双审 Gold”。
