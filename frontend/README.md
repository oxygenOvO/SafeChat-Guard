# Streamlit 比赛展示控制台

本目录整合自 D 组前端交付，并已替换其中的演示检测逻辑。

## 数据来源

- 输入检测：`SafeChatPipeline.filter_input()`
- 输出检测：`SafeChatPipeline.filter_output()`
- 归一化轨迹：`TextNormalizer.normalize_with_trace()`
- 规则配置：当前 `RuleFilter` 实际加载结果
- 日志审计：`EventLogger` 的 JSONL 日志
- 批量样例：`data/test_cases/frontend_cases.csv`

页面不会生成固定风险分数或固定价值观评分。尚未由后端实现的能力，应在后端
完成并经过测试后再加入展示。

## 启动

```powershell
python -m pip install -r requirements.txt
python -m streamlit run frontend/streamlit_app.py
```
