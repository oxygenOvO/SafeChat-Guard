# 独立评估集 V1 完成批次覆盖说明（138 条）

## 覆盖范围

最终审核表 `../semantic_independent_eval_v1_final_review_completed.csv` 共 200 条，包含 200 个唯一 `sample_id`。

本目录保存最终审核过程中形成的 7 个完成批次，共 138 条、138 个唯一 `sample_id`。这些批次不是完整 200 条批次。另有 62 条样本在形成这 7 个批次前已经完成，因此不包含在本目录中。

`batch_manifest.csv` 中每批 `count` 与对应 CSV 的实际行数一致。批次类别和动作分布按 `sample_id` 与最终审核表回连复核。

## 批次快照的生成方式

这 7 个文件最初用于分批审核。当前仓库中归档的是根据最终审核表回填生成的最终审核快照：批次成员和 `sample_id` 顺序沿用原始批次，审核状态、reviewer 和 notes 以 200 条最终审核表为唯一权威来源。

这些批次不是第二次独立审核，也不能视为双人复核。

## 提前完成的 62 条

| 类别 | 动作 | 数量 |
|---|---|---:|
| normal | pass | 10 |
| ad | sanitize | 10 |
| ad | block | 3 |
| porn | sanitize | 10 |
| porn | block | 3 |
| violence | sanitize | 10 |
| violence | block | 3 |
| sensitive | sanitize | 10 |
| sensitive | block | 3 |

## 本目录完成批次的 138 条

| 类别 | 动作 | 数量 |
|---|---|---:|
| normal | pass | 90 |
| ad | block | 12 |
| porn | block | 12 |
| violence | block | 12 |
| sensitive | block | 12 |
| 全部类别 | sanitize | 0 |

## ID 覆盖关系

138 条完成批次与提前完成的 62 条的 `sample_id` 集合互不重复。两部分合并后，与最终审核表的 200 个 `sample_id` 完全一致：

`138 + 62 = 200`

## 最终 200 条分布

| 类别 | 动作 | 数量 |
|---|---|---:|
| normal | pass | 100 |
| ad | sanitize | 10 |
| ad | block | 15 |
| porn | sanitize | 10 |
| porn | block | 15 |
| violence | sanitize | 10 |
| violence | block | 15 |
| sensitive | sanitize | 10 |
| sensitive | block | 15 |

动作合计：

- pass：100；
- sanitize：40；
- block：60。

## 审核与使用边界

当前审核状态属于单人独立审核结果，不是双人复核 Gold，也不得描述为双人复核 Gold。

这些数据不得用于训练，只用于独立评估和错误分析。
