# 逐步开始指南

## 第 0 步：今天只做三件事

1. 把项目跑起来。
2. 看懂系统从输入到输出的流程。
3. 开始整理四类词库和测试样例。

## 第 1 步：运行项目

```powershell
cd C:\Users\Lenovo\Documents\Codex\2026-07-04\new-chat\SafeChat-Guard
python app.py
```

浏览器打开：`http://127.0.0.1:8000`

## 第 2 步：先测通流程

可以先输入：

```text
hello safety contest
please add me for agent service
call me at 13812345678
violence_placeholder
```

看到 pass、sanitize、block 三类结果后，就说明骨架通了。

## 第 3 步：A 组整理词库

编辑这些文件：

```text
data/lexicons/porn.txt
data/lexicons/violence.txt
data/lexicons/ad.txt
data/lexicons/sensitive.txt
data/rules/regex_rules.json
data/maps/homophone_map.json
data/maps/emoji_map.json
```

每类先整理 30 到 50 个高频样例。每加一批词，就补 5 到 10 条测试用例。

## 第 4 步：B 组做语义分类

建议顺序：

1. 先用当前 `SemanticClassifier` 的占位版本跑通。
2. 找一个开源中文文本分类模型或安全分类 API 做替换。
3. 输出统一格式：类别、风险等级、分数、原因。
4. 最后再考虑接入大创里的 XLM-R / RoBERTa。

## 第 5 步：C 组完善后端

优先事项：

1. 保证 `/api/chat` 稳定返回。
2. 增加词库导入、添加、删除接口。
3. 增加日志查询接口。
4. 把 Qwen API 接入 `llm_client.py`。

## 第 6 步：D 组完善前端和文档

优先事项：

1. 页面展示输入检测结果、输出检测结果。
2. 展示命中类别、风险分数、处理动作。
3. 展示统计图或统计表。
4. 每完成一个功能就截图，后续直接放进作品报告。

## 第一周验收标准

- 能启动 Web 页面。
- 能输入文本并返回模拟大模型回复。
- 能拦截高风险词。
- 能脱敏广告/联系方式。
- 能记录日志。
- 有不少于 30 条测试用例。
- 有一版系统架构图和模块分工表。
