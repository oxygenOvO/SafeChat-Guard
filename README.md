# SafeChat-Guard

面向中文对话场景的大模型输入/输出违规内容过滤与日志统计系统。

本项目用于人工智能安全竞赛定向题目：面向对话场景的大模型输入/输出违规内容过滤系统。

## 核心功能

- 输入侧过滤：关键词、正则、归一化后的违规内容检测。
- 语义二次判定：可接入轻量分类模型；缺少模型依赖时自动降级，不影响规则链路运行。
- 分级处理：高风险拦截，中低风险脱敏/改写，正常内容放行。
- 输出侧二次校验：对大模型回复再次检测，命中违规内容时拦截或脱敏改写。
- 日志统计：记录每次请求的检测结果、处理动作、风险类别、风险等级和命中规则。
- Web Demo：提供 Streamlit 安全控制台，以及 `/api/chat`、`/api/detect`、`/api/stats` 接口。

## 成员 C 交付内容

成员 C 负责输出校验、脱敏改写和日志统计，主要文件：

```text
safechat_guard/output_guard.py
safechat_guard/logger.py
safechat_guard/pipeline.py
tests/test_output_guard.py
```

输出侧覆盖类别：

- 色情低俗
- 暴力威胁
- 广告引流
- 敏感话术
- 违法违规
- 自伤自杀
- 隐私泄露

日志采用输入、输出、最终动作分阶段记录；用户输入、模型原始输出和最终文本统一脱敏，仅保留安全审计所需的时间、阶段、类别、风险、动作与命中统计。

日志默认保存到：

```text
data/logs/events.jsonl
```

## D 组前端安全集成

比赛控制台位于 `frontend/streamlit_app.py`，展示归一化、规则与语义联合检测、分级动作、输出复检、聚合审计和批量评测。适配层以 `SafeChatPipeline.handle_chat` 的公开结果作为唯一最终安全结论：高风险输入不会调用 LLM，服务不可用时显示安全降级状态，风险模型输出不会进入前端视图模型或导出日志。

`data/test_cases/frontend_demo_cases_v2.csv` 的 8 条内置样例全部属于功能 Demo，仅用于页面回归统计，不代表正式独立评估结果。正式指标仍以冻结的 `single_review_independent_gold_v1` 记录为准。

启动控制台：

```powershell
streamlit run frontend/streamlit_app.py
```
## 快速运行

```powershell
python app.py
```

浏览器访问：

```text
http://127.0.0.1:8000
```

## 基础检查

如果已安装 pytest：

```powershell
python -m pytest tests
```

如果没有 pytest，也可以直接做语法检查：

```powershell
python -B -c "from pathlib import Path; files=list(Path('safechat_guard').glob('*.py'))+list(Path('tests').glob('*.py'))+[Path('app.py')]; [compile(p.read_text(encoding='utf-8'), str(p), 'exec') for p in files]; print('syntax ok')"
```

## 接口说明

启动 `app.py` 后：

- `POST /api/chat`：提交用户输入，返回输入过滤、模型回复、输出过滤结果。
- `GET /api/stats`：返回日志统计，包括总事件数、拦截数、改写数、类别分布、风险等级分布。

## 目录结构

```text
safechat_guard/
  pipeline.py             # 主流程
  output_guard.py         # 输出侧二次校验与脱敏改写
  logger.py               # JSONL日志与统计
  rule_filter.py          # 关键词/正则检测
  normalizer.py           # 中文对抗归一化
  semantic_classifier.py  # 语义分类器，可选依赖
data/
  lexicons/               # 违规词库
  rules/                  # 正则规则
templates/                # 前端页面
static/                   # 前端样式与脚本
tests/                    # 测试用例
```
