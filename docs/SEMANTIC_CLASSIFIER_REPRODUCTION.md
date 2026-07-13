# 中文语义分类器复现实验说明

## 模型目标

当前语义分类器把中文文本分为 `normal`、`ad`、`porn`、`violence` 和
`sensitive`。它是基于文本统计特征的轻量分类模型，不等同于关键词过滤器；
`RuleFilter` 仍独立提供词库和正则证据。

## 数据格式

训练脚本读取 `data/training_data/raw_train_v3.csv`，包含 `text` 与 `label`：

```csv
text,label
加微信领取资料,ad
请介绍网络安全基础知识,normal
```

## 当前轻量基线

仓库使用无需 GPU 的 scikit-learn Pipeline：

- `TfidfVectorizer`
- `ngram_range=(1, 2)`
- `max_features=10000`、`min_df=2`、`max_df=0.8`
- `LogisticRegression`
- `class_weight="balanced"`、`random_state=42`
- 通过 `joblib` 保存为 `models/semantic_model.pkl`

## 训练命令

```powershell
python scripts\prepare_data_v3.py
python scripts\train_classifier.py
```

模型加载状态可以通过后端 `pipeline.stats()` 或 API 服务的 `/api/stats` 查看。
模型不存在、依赖缺失或加载失败时，状态中会包含明确错误，规则过滤链路仍可继续运行。

## 联调接口

启动 API 服务：

```powershell
python api_server.py
```

请求：

```http
POST /api/detect
Content-Type: application/json

{"text": "加 V-X 领取优 惠 券"}
```

返回字段包括 `model_loaded`、`detections`、`model_error`、`normalized_text`
和 `semantic_scores`，便于前端先按照固定结构完成渲染。

## 局限性

轻量模型高度依赖训练数据，对隐喻、反讽和复杂上下文能力有限，不能替代
XLM-R、RoBERTa 或 LLM 分类器。正式参赛前还需要独立测试集、误报分析、
概率校准和持续数据治理。
