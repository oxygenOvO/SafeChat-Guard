# SafeChat-Guard

面向中文对话场景的大模型输入/输出违规内容过滤与日志统计系统。

本项目用于人工智能安全竞赛定向题目：面向对话场景的大模型输入/输出违规内容过滤系统。

最终竞赛提交冻结版本为 `1286f3db3e5e73f6ad7543cdbd47ed9227235b5c`（短哈希 `1286f3d`）。`93105e5` 是 earlier/pre-final delivery baseline，不是最终竞赛提交版本。本次仅对齐交付文档；不改变源码、模型、阈值、规则、配置或评估结果。

## 核心功能

- 输入侧过滤：关键词、正则、归一化后的违规内容检测。
- 语义二次判定：可接入轻量分类模型；缺少模型依赖时自动降级，不影响规则链路运行。
- 分级处理：高风险拦截，中低风险脱敏/改写，正常内容放行。
- 输出侧二次校验：对大模型回复再次检测，命中违规内容时拦截或脱敏改写。
- 日志统计：记录每次请求的检测结果、处理动作、风险类别、风险等级和命中规则。
- Web Demo：提供 Streamlit 安全控制台，以及 `/api/chat`、`/api/detect`、`/api/stats` 接口。

V3 正式启用的对抗归一化能力主要覆盖 Unicode/控制字符、符号插入、Emoji、同音、拼音、缩写、重复噪声及受控拆分恢复。系统预留 `variant_char` 形近字扩展接口，但冻结版本的 `data/maps/variant_char_map.json` 为空，未将形近字恢复作为正式启用能力。

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

输入侧与输出侧使用不同的动作边界。输入侧由 RuleFilter、SemanticClassifier 和结构化证据进入 ActionRouterV3；输入 sanitize 后，Sanitizer 对 normalized text 中已定位的 match 做局部改写并重新扫描、重新路由。该 Sanitizer 不是完整的结构化隐私字段正则系统。输出侧由独立 OutputGuard 使用基础扫描证据、自有 80/40 阈值、privacy regex 和 extra high-risk rules 进行 sanitize 或安全拒绝；它不会把模型输出重新完整送入 ActionRouterV3。

核心训练/输入风险标签空间仍为 `normal`、`ad`、`porn`、`violence`、`sensitive`。OutputGuard 的 `privacy`、`illegal`、`self_harm` 等属于输出安全运行时扩展类别；`abuse` 具有输出侧标签和安全响应支持，不与核心五分类训练标签混为一谈。

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
python api_server.py
```

浏览器访问：

```text
http://127.0.0.1:8000
```

## 基础检查

如果已安装 pytest：

```powershell
python -m pytest -q --basetemp=.test_tmp
```

最终竞赛冻结提交 `1286f3d` 在干净 frozen clone 中收集到 `594 collected`，实测为 `594 passed, 1297 warnings in 79.27s`。`576 passed` 是 earlier/pre-final delivery baseline，不再是 final submission test count。上述测试均不包含重新运行 internal holdout。

如果没有 pytest，也可以直接做语法检查：

```powershell
python -B -c "from pathlib import Path; files=list(Path('safechat_guard').glob('*.py'))+list(Path('tests').glob('*.py'))+[Path('app.py')]; [compile(p.read_text(encoding='utf-8'), str(p), 'exec') for p in files]; print('syntax ok')"
```

## 接口说明

启动唯一正式入口 `api_server.py` 后：

`app.py` 仅保留为兼容启动包装器，复用相同服务器、配置解析、请求校验和异常处理。

- `POST /api/chat`：提交用户输入，返回输入过滤、模型回复、输出过滤结果。
- `GET /health`：进程存活检查。
- `GET /ready`：语义模型与LLM运行状态检查。
- `POST /api/detect`：仅执行输入检测链路。
- `GET /api/stats`：返回日志统计，包括总事件数、拦截数、改写数、类别分布、风险等级分布。
- `GET/POST/PATCH/DELETE /api/rules`：管理独立用户规则 overlay；内置规则只读。
  - 用户 `block` 规则在 ActionRouter 前可信校验并直接拦截；`sanitize` 规则继续走脱敏与复检。
- `POST /api/rules/import`：原子导入 UTF-8 CSV/JSON，支持 `dry_run`。
- `GET /api/stats/summary`、`/api/stats/daily`：基于 `request_summary` 的请求级每日统计。

## 目录结构

```text
safechat_guard/
  pipeline.py             # 主流程
  output_guard.py         # 输出侧二次校验与脱敏改写
  logger.py               # JSONL日志与统计
  rule_filter.py          # 关键词/正则检测
  rule_manager.py         # 用户规则CRUD、校验与原子存储
  normalizer.py           # 中文对抗归一化
  semantic_classifier.py  # 语义分类器，可选依赖
data/
  lexicons/               # 违规词库
  rules/                  # 正则规则
templates/                # 前端页面
static/                   # 前端样式与脚本
tests/                    # 测试用例
```
### User-rule privacy and activation

Rule patterns are redacted by default in rule list/get and mutation responses. Full patterns require an explicit `include_pattern=true` read that passes the same loopback/admin-token policy used by management writes. The Streamlit rule page enables full-pattern editing only after its authorized-management mode succeeds.

Rule changes use candidate compilation followed by atomic persistence and snapshot activation. If activation fails, the previous file, revision, and in-memory RuleFilter snapshot are restored. A rollback failure enters a degraded state that preserves the last trusted in-memory rules and rejects later writes.

## V3正式交付说明

生产链路依次执行文本归一化、关键词与正则检测、语义分类、动作路由、必要的脱敏与复检、LLM调用以及输出二次校验。当前语义层是使用自建训练数据训练的 **TF-IDF + LogisticRegression** 轻量分类器，不是预训练Transformer模型，也不应按预训练模型宣传。

V3冻结版本在自建、一次性运行的330条 `internal_holdout` 上得到：Accuracy 99.39%、Block Recall 100%、Sanitize Recall 100%、Normal FPR 1.54%。这些是项目内部留出集指标，不是官方隐藏测试结果；该留出集仅正式运行一次，运行后未调参、未重跑。

生产一致性 `170/170` 证明冻结 V3 的直接检测入口与生产对话入口在公开非 holdout 矩阵上的动作和标签一致，不等同于真实世界泛化准确率。200 条人工复核 Gold 当前口径为 provisional single-review gold；第二 reviewer 的 40 条 blind sample 尚未完成时，不称已完成双人独立审核。

默认 [config.yaml](config.yaml) 始终使用 `mock`，用于离线演示和自动测试，不产生外部调用，也不能作为真实联网证据。真实LLM模式必须显式选择 [config.real_llm.example.yaml](config.real_llm.example.yaml)；该示例使用 `qwen` provider，密钥只从进程环境变量 `DASHSCOPE_API_KEY` 读取，配置文件不保存密钥。

2026-07-31 已完成真实 Qwen 联网验证：provider=`qwen`、model=`qwen-plus`、status=`passed`，真实上游调用 2 次。五项验收均通过：`pass_forwarded=true`、`block_not_forwarded=true`、`sanitize_forwarded_after_redaction=true`、`upstream_failure_closed_safely=true`、`unsafe_output_blocked=true`。验收输出未打印凭据（`credentials_printed=false`），运行后已清除进程环境变量 `DASHSCOPE_API_KEY`；文档不记录 API key、Authorization 头、提示词或模型原始回答。上游异常和违规输出两项使用本地注入式安全路径测试，不表示 DashScope 发生过真实故障。

### 真实LLM启动

先通过操作系统、CI或密钥管理平台向进程环境注入 `DASHSCOPE_API_KEY`，不要把真实值写入命令历史、`.env.example`、日志或截图。随后在PowerShell会话中选择示例配置：

```powershell
$env:SAFECHAT_CONFIG_PATH = "config.real_llm.example.yaml"
python api_server.py
```

检查运行状态：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/ready
```

`llm.ready` 应为 `true`，`provider` 应为 `qwen`。示例使用阿里云百炼OpenAI-compatible HTTPS endpoint；区域、模型权限和计费以供应商账号为准。

### 真实LLM安全冒烟

获授权人员执行以下脚本时会产生两次真实上游调用：一次正常放行输入、一次脱敏后的输入。高风险不调用、上游异常安全失败和违规输出拦截使用本地受控注入验证，因此不会诱导真实模型生成违规内容。未配置授权密钥和网络时不要执行，也不得把离线测试结果表述为真实联网成功。

```powershell
python scripts/smoke_real_llm.py --config config.real_llm.example.yaml
```

脚本只输出布尔验收结果、provider、model和调用次数，不输出API key、请求正文或模型回复。成功条件包括：

- pass输入确实调用上游；
- block输入不调用上游；
- sanitize输入仅把脱敏后的文本传给上游；
- 上游异常返回安全的 `llm_unavailable`；
- 上游违规输出被OutputGuard拦截。

完整运行、运维和故障处理见 [docs/OPERATIONS.md](docs/OPERATIONS.md)，需求证据见 [docs/REQUIREMENT_TRACEABILITY.md](docs/REQUIREMENT_TRACEABILITY.md)。
