# SafeChat-Guard

面向中文对话场景的大模型输入/输出违规内容过滤与日志统计系统。

本项目用于 2026 第二届大学生人工智能安全竞赛题目 1：面向对话场景的大模型输入/输出违规内容过滤系统。

## 核心功能

- 输入侧过滤：关键词、正则和中文对抗文本归一化。
- 中文归一化：Unicode、变体字、谐音、拼音、缩写、表情和干扰字符处理。
- 语义二次判定：默认使用中文规则，可选加载轻量机器学习模型。
- 分级处理：高风险拦截，中风险脱敏，正常内容放行。
- 输出侧校验：再次检测模型回复，并处理违规内容和隐私信息。
- 日志统计：记录风险类别、等级、处理动作和命中规则。
- Web Demo：提供网页界面以及 `/api/chat`、`/api/stats` 接口。

## 处理流程

用户输入 -> 文本归一化 -> 关键词/正则过滤 -> 语义分类 -> 分级处理 -> 调用模型 -> 输出保护 -> 日志与统计。

## 快速运行

基础规则版本只需要 Python 3.11+：

```powershell
python app.py
```

浏览器访问：

```text
http://127.0.0.1:8000
```

训练或加载可选的轻量语义模型时，再安装：

```powershell
python -m pip install -r requirements.txt
python scripts/prepare_data_v3.py
python scripts/train_classifier.py
```

模型默认保存为 `models/semantic_model.pkl`。模型或相关依赖不存在时，系统会自动使用中文规则分类器。

## 基础检查

```powershell
python -m pytest tests
```

未安装 pytest 时，也可以运行语法检查：

```powershell
python -m compileall safechat_guard tests
```

## 主要目录

```text
safechat_guard/
  normalization/          # 模块化文本归一化管道
  normalizer.py           # 兼容入口
  rule_filter.py          # 关键词与正则检测
  semantic_classifier.py  # 中文规则与可选轻量模型
  output_guard.py         # 输出侧校验、隐私脱敏与安全回复
  pipeline.py             # 主流程
  logger.py               # JSONL 日志与统计
data/
  lexicons/               # 分类词库
  maps/                   # 归一化映射表
  rules/                  # 正则规则
  test_cases/             # 回归测试样例
  violation_sentences/    # 语义模型训练语料
scripts/                  # 数据准备与模型训练脚本
tests/                    # 自动化测试
```

## 协作说明

当前版本已合并输入归一化、中文语义分类、输出侧保护和日志统计。词库、映射表和训练语料应分别维护，避免把训练语料直接混入关键词词库造成类别污染。
