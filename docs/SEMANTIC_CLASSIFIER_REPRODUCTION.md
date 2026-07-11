# 中文语义分类器复现实验说明

## 模型目标

当前分类器把中文文本分为 `normal`、`ad`、`porn`、`violence` 和
`sensitive`。它是基于文本统计特征的分类模型，不等同于关键词过滤器；
`RuleFilter` 仍独立提供词库和正则证据。

## 数据格式

训练脚本读取 `data/training_data/raw_train_v3.csv`，包含 `text` 与 `label`：

```csv
text,label
加微信领取资料,ad
请介绍网络安全基础知识,normal
```

若使用 JSONL，推荐结构如下，训练前需转换成上述 CSV：

```json
{"text": "加微信领取资料", "label": "ad"}
{"text": "请介绍网络安全基础知识", "label": "normal"}
```

## 数据划分

现有脚本按 80%/20% 分层划分训练集和测试集，固定 `random_state=42`。
正式实验应从训练数据中另划验证集，并按原始样本或模板分组划分，避免同一
模板的变体同时进入训练集与测试集。正常类应覆盖否定、引用、教育和安全研究
语境，以评估误报。

## 当前轻量基线

仓库使用无需 GPU 的 scikit-learn Pipeline：

- `TfidfVectorizer`，默认 word analyzer；
- `ngram_range=(1, 2)`；
- `max_features=10000`、`min_df=2`、`max_df=0.8`；
- `LogisticRegression`，`C=10.0`、`max_iter=1000`；
- `class_weight="balanced"`、`random_state=42`；
- 通过 `joblib` 保存为 `models/semantic_model.pkl`。

## 训练命令

```bash
python scripts/prepare_data_v3.py
python scripts/train_classifier.py
```

训练脚本读取真实 CSV、固定随机种子、输出评估结果并保存模型，不依赖大型
深度学习模型。

## 评估指标

脚本输出 accuracy、macro precision、macro recall、macro F1、各类别的
precision/recall/F1 和 confusion matrix。本文不填写未在当前数据与环境中
实际运行得到的数值。

## 完整复现步骤

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
python scripts/prepare_data_v3.py
python scripts/train_classifier.py
pytest -q
python app.py
```

模型加载状态通过现有 `/api/stats` 返回。模型不存在、依赖缺失或加载失败时，
状态中会包含明确错误，规则过滤链路仍可继续运行。

## 局限性

轻量模型高度依赖训练数据，对隐喻、反讽和复杂上下文能力有限，不能替代
XLM-R、RoBERTa 或 LLM 分类器。当前实现只是比赛工程基线，正式部署还需要
独立测试集、误报分析、概率校准和持续数据治理。
