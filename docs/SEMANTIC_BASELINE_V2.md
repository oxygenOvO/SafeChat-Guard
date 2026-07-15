# 中文语义分类基线 V2

## 定位与限制

本基线只使用文本所在来源目录继承的弱标签（`source_type=weak_label`），用于验证中文文本分类训练、加载和评估链路。所有指标的评估范围均标记为 `weak_label_grouped_holdout`，并明确设置 `official_competition_metric=false`。

这些结果不是正式竞赛指标。当前尚未建立与训练来源独立、经过人工确认的 gold 测试集，因此不能据此声称项目已经达到正式的泛化效果。本版本不沿用旧语义分支中 94.89% 或 98.12% 的结论。

## 数据与拆分

训练源仅为：

- `data/normal_sentences.txt`
- `data/violation_sentences/ad.txt`
- `data/violation_sentences/porn.txt`
- `data/violation_sentences/violence.txt`
- `data/violation_sentences/sensitive.txt`

构建时清除空行，保留 `original_text`，并使用项目 `TextNormalizer` 生成 `normalized_text`。`group_id` 是 `SHA-256(normalized_text)`，不使用 Python 进程相关的内置 `hash()`。

数据先隔离同一 `normalized_text` 对应多个标签的冲突组，再去除精确重复和规范化等价重复。随后以固定随机种子 42，在每个标签内对唯一 `group_id` 做确定性 70%/15%/15% 的 train/validation/test 拆分。拆分前不复制、不扩增、不过采样；分类器通过 `class_weight="balanced"` 处理类别不平衡。

构建器会审计精确文本、NFKC 文本和项目 Normalizer 文本是否跨拆分泄漏。`data/evaluation/` 不在数据源允许列表中，任何评估 CSV 均不会作为训练输入。

## 模型比较与选择

两个模型读取同一份 `split_manifest.csv`：

| 模型 | TF-IDF | 分类器 |
|---|---|---|
| Word | `analyzer="word"`, `ngram_range=(1, 2)` | LogisticRegression |
| Char | `analyzer="char"`, `ngram_range=(2, 5)` | LogisticRegression |

两个分类器都设置 `class_weight="balanced"`、`random_state=42`、`max_iter=2000`。仅使用 validation 的 macro-F1（相同时再比较 accuracy）选择模型，不使用 test 指标做选择。选择规则锁定后，两个候选模型各在 test 上评估一次，以保留公平比较证据；最终模型仍仅由 validation 决定。

本次实际弱标签分组留出结果：

| 模型 | Validation accuracy | Validation macro-F1 | Test accuracy | Test macro-F1 |
|---|---:|---:|---:|---:|
| Word | 0.3231 | 0.0977 | 0.3231 | 0.0977 |
| Char | 0.6769 | 0.6291 | 0.5385 | 0.4877 |

因此选择 Char 模型。Word 模型在当前无空格中文短文本上几乎全部预测为 normal，结果也作为失败基线如实保留。Char 测试集 `normal_false_positive_rate=0.1429`、`risk_recall=0.6136`。这些数值仅描述当前弱标签留出集。

## 复现命令

在仓库根目录、UTF-8 Python 环境中依次运行：

```bash
python scripts/prepare_semantic_data_v2.py
python scripts/train_semantic_baseline_v2.py
python scripts/evaluate_semantic_baseline_v2.py
```

随后验证：

```bash
python -m pytest -q -p no:cacheprovider --basetemp=.test_tmp
python -m compileall app.py safechat_guard scripts tests
git diff --check
```

模型保存为 `models/semantic_model_v2.joblib`，继续受 `.gitignore` 排除，不提交二进制文件。报告和可审计清单位于 `reports/semantic_baseline_v2/`，其中包含源文件哈希、拆分清单、重复/冲突/泄漏报告、两个模型的验证与测试指标、混淆矩阵、运行配置和模型元数据。
