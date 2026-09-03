# SafeChat-Guard V1.0

统一网页对话入口、多模型接入、输入/输出双向安全检测的大模型安全网关。

SafeChat-Guard 面向对话场景，对所有进入大模型的内容做输入侧违规检测与脱敏改写，
对所有模型输出做二次复检，高风险内容直接拦截，确保到达用户的内容安全合规。
系统默认使用无需任何密钥的离线 Mock 模型，可一键切换到 DeepSeek、通义 Qwen
（DashScope / NSCC MaaS）等真实大模型。

## 核心功能

### 输入侧检测链路

- **对抗归一化**：覆盖 Unicode/控制字符、符号插入、Emoji、同音替换、拼音、
  缩写、重复噪声及受控拆分恢复，还原变体攻击后的真实文本。
- **关键词与正则检测**：基于内置违规词库与正则规则库，支持用户自定义规则叠加。
- **语义二次判定**：自建语料训练的 TF-IDF + LogisticRegression 轻量分类器，
  对归一化文本做五分类（normal / ad / porn / violence / sensitive）；
  模型缺失时自动降级，不影响规则链路运行。
- **分级动作路由**：高风险拦截（不调用模型）、中低风险脱敏改写后复检、
  正常内容放行。

### 输出侧二次校验

- 独立 OutputGuard 对模型回复再次扫描：隐私字段掩码（手机号、邮箱、身份证、
  银行卡、链接、IP、微信号、QQ、地址）、高危词库命中检测。
- 风险输出按阈值拦截（返回类别化安全答复）或脱敏改写；有风险且无法安全改写时
  不向用户展示模型原文。
- 输入、输出使用不同动作边界与阈值体系，互不越界。

### 多模型接入

- 内置 Provider：**Offline Mock**（默认，零配置）、**DeepSeek**、
  **通义 Qwen**（DashScope）、**Qwen3.5**（NSCC-CS MaaS），
  全部走 OpenAI-compatible 协议。
- API Key 仅从环境变量读取，不落盘、不进日志；密钥未配置时 Provider 显示
  “未配置”，不产生真实调用。
- 网页端“模型管理”页可启用/停用 Provider、设置默认模型并执行真实连接测试。

### 多轮对话

- “安全对话”页支持多轮上下文：每轮自动携带最近 20 条历史（含角色与内容）。
- 传给模型的新消息始终是**脱敏后**的文本；历史中的内容均为已通过双向检测的内容。
- 高风险输入依旧直接拦截，历史与新消息都不会转发给模型。

### 会话管理

- 侧边栏支持新建对话、历史会话切换、删除会话，会话按最近更新排序。
- 会话持久化到本地 `data/runtime/chat_sessions.json`（该目录已被 Git 忽略），
  重启后自动恢复最近一次会话；存储采用原子写入，文件损坏时自动重建。
- 单会话最多保留 200 条消息，最多保留 100 个会话。

### 用户自定义规则

- 独立用户规则 overlay：增删改查、批量导入（UTF-8 CSV/JSON，支持 dry_run）、
  版本化存储与快照回滚。
- 用户 `block` 规则在路由前可信校验并直接拦截；`sanitize` 规则继续走
  脱敏与复检流程。
- 规则列表默认脱敏展示 pattern，完整 pattern 需管理员授权读取；
  内置规则只读。

### 审计与统计

- 每次请求生成不含个人信息的 `request_id`，关联输入检测、模型调用、
  输出复检与最终动作，分阶段写入 JSONL 日志（`data/logs/events.jsonl`）。
- 日志中用户输入、模型原始输出与最终文本统一脱敏，仅保留审计所需字段。
- 提供请求数、拦截数、改写数、类别分布、风险等级分布、每日趋势等统计。

## 快速开始

### 环境要求

- Python 3.11 及以上
- 依赖见 `requirements.txt`（scikit-learn、streamlit、plotly 等）

### 安装依赖

```powershell
python -m pip install -r requirements.txt
```

### 启动网页控制台（推荐）

```powershell
python -m streamlit run frontend/streamlit_app.py
```

浏览器访问 `http://localhost:8501`。默认离线 Mock 模式，无需任何配置即可体验
完整安全检测链路。控制台包含以下页面：

| 页面 | 功能 |
| --- | --- |
| 安全对话 | 多轮安全对话，实时展示输入/输出检测结论与详情 |
| 系统总览 | 实时聚合 PASS / SANITIZE / BLOCK 请求概况 |
| 模型管理 | Provider 启用、默认模型设置、真实连接测试 |
| 安全策略 | 用户规则管理与安全策略查看 |
| 安全日志 | 脱敏请求摘要，支持时间/动作/类别/Provider 筛选与 CSV 导出 |
| 风险统计 | 动作、风险类别与时间趋势图 |
| 安全评测 | 多检测模式对比、批量样本评估、指标导出 |
| 系统状态 | Pipeline、安全组件与 Provider 健康检查（Fail-Closed 展示） |
| 系统设置 | 只读展示运行配置 |

### 启动 HTTP API 服务

```powershell
python api_server.py
```

浏览器访问 `http://127.0.0.1:8000`。`app.py` 仅保留为兼容启动包装器，
复用同一服务器与配置解析。

## 接入真实大模型

API Key 全部通过环境变量注入，不要把真实密钥写入源码、配置或文档。

| Provider | 环境变量 | 说明 |
| --- | --- | --- |
| DeepSeek | `DEEPSEEK_API_KEY` | 模型 `deepseek-chat` |
| 通义 Qwen | `DASHSCOPE_API_KEY` | 模型 `qwen-plus`（DashScope 兼容模式） |
| Qwen3.5 | `NSCC_MAAS_API_KEY` | NSCC-CS MaaS，模型 `Qwen3.5` |

推荐在系统中永久配置用户环境变量，例如（PowerShell）：

```powershell
[Environment]::SetEnvironmentVariable("DEEPSEEK_API_KEY", "你的密钥", "User")
```

随后在控制台“模型管理”页：选择 Provider → 测试连接 → 保存启用状态 →
设为默认模型，即可在“安全对话”页使用真实模型。

也可以通过配置文件显式切换默认 Provider：

```powershell
$env:NSCC_MAAS_API_KEY = "你的密钥"
$env:SAFECHAT_CONFIG_PATH = "config.real_llm.example.yaml"
python api_server.py
```

检查运行状态（`llm.ready` 应为 `true`）：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/ready
```

真实链路冒烟脚本（会产生两次真实上游调用，仅输出布尔验收结果）：

```powershell
python scripts/smoke_real_llm.py --config config.real_llm.example.yaml
```

## HTTP API 说明

| 方法与路径 | 说明 |
| --- | --- |
| `POST /api/chat` | 安全对话：提交消息与可选历史，返回输入过滤、模型回复、输出复检结果 |
| `POST /api/detect` | 仅执行输入检测链路 |
| `GET /health` | 进程存活检查 |
| `GET /ready` | 语义模型与 LLM 就绪状态检查 |
| `GET /api/stats` | 日志统计：总事件数、拦截数、改写数、类别与风险分布 |
| `GET /api/stats/summary` `/api/stats/daily` | 请求级汇总与每日统计 |
| `GET/POST/PATCH/DELETE /api/rules` | 用户规则管理（内置规则只读） |
| `POST /api/rules/import` | 原子导入 UTF-8 CSV/JSON，支持 `dry_run` |

对话请求示例（`history` 可选，最多 20 条）：

```json
POST /api/chat
{
  "message": "那第二个方案呢？",
  "history": [
    {"role": "user", "content": "第一个方案是什么？"},
    {"role": "assistant", "content": "第一个方案是……"}
  ]
}
```

返回结果中包含 `input_filter`（输入检测结论）、`reply`（最终安全回复）、
`output_filter`（输出复检结论）、`final_action` 与 `model_forwarded`
（是否真实调用了模型）等字段。

## 目录结构

```text
safechat_guard/            # 核心安全检测包
  pipeline.py              # 主流程：输入过滤 → 模型调用 → 输出复检
  normalizer.py            # 中文对抗归一化
  normalization/           # 归一化子包（Provider、映射归一器）
  rule_filter.py           # 关键词/正则检测
  rule_manager.py          # 用户规则 CRUD、校验与原子存储
  rule_management_service.py  # 规则管理服务与内置规则策略
  semantic_classifier.py   # TF-IDF + LR 语义分类器（可选依赖）
  action_router.py         # V2 动作路由
  action_router_v3.py      # V3 证据增强路由
  sanitizer.py             # 输入侧脱敏改写
  output_guard.py          # 输出侧二次校验与隐私掩码
  llm_client.py            # OpenAI-compatible LLM 客户端
  llm_adapters.py          # Provider 适配层（Mock/Qwen/DeepSeek）
  model_registry.py        # Provider 运行时注册表
  logger.py                # JSONL 审计日志与统计
  audit_service.py         # 审计查询服务
  analytics_service.py     # 统计分析服务
  health_service.py        # 组件健康检查
  evaluation_service.py    # 安全评测服务
  decision_explanation_service.py  # 决策解释服务
  provider_diagnostics.py  # Provider 错误分类与脱敏诊断
api_server.py              # 唯一正式 HTTP API 入口
app.py                     # 兼容启动包装器
frontend/                  # Streamlit 控制台
  streamlit_app.py         # 唯一网页入口
  chat_app.py              # 安全对话页（多轮对话 + 会话管理）
  session_store.py         # 本地会话持久化
  phase2_app.py            # 运维控制台外壳（九页导航）
  management_views.py      # 管理/日志/统计页面
  security_platform_views.py  # 安全策略与安全评测页面
  adapter.py               # Pipeline 与前端之间的视图模型适配层
config/                    # 路由阈值、语义阈值等运行配置
data/
  lexicons/                # 违规词库
  rules/                   # 正则规则
  maps/                    # 归一化映射表（同音、Emoji、拼音等）
  runtime/                 # 运行时状态（模型注册表、聊天会话，已 gitignore）
  logs/                    # JSONL 审计日志（已 gitignore）
  test_cases/              # 内置演示用例
models/                    # 语义分类模型（joblib）
templates/ static/         # 早期 Web Demo 页面资源
tests/                     # pytest 测试用例
scripts/                   # 评测、冒烟与运维脚本
docs/                      # 运维手册、需求追溯等文档
```

## 配置说明

- 默认配置 `config.yaml`：`app`（监听地址/端口）、`api`（请求大小与文本长度上限）、
  `risk`（block/sanitize 阈值）、`semantic`（分类器配置）、`action_v3`（V3 路由开关）、
  `llm`（Provider 与模型）、`logging`（日志路径与轮转）。
- 通过环境变量 `SAFECHAT_CONFIG_PATH` 指向其他配置文件即可整体切换，
  例如 `config.real_llm.example.yaml`。
- 所有 Provider 的 `api_key_env` 均指向环境变量名，配置文件中不出现明文密钥。

## 安全设计

- **Fail-Closed**：关键安全组件异常时暂停模型调用，管理页明确展示降级状态；
  上游模型异常时返回安全兜底话术。
- **最小化存储**：审计日志分阶段脱敏；聊天会话与运行时状态均位于被 Git 忽略的
  `data/runtime/`；密钥只存在于进程环境变量。
- **管理面保护**：规则写操作需 `SAFECHAT_ENABLE_RULE_WRITES=true` 且通过
  管理令牌（`SAFECHAT_RULE_ADMIN_TOKEN`）授权，采用恒时比较与回环地址校验。
- **规则原子变更**：候选编译 → 原子持久化 → 快照激活，失败自动回滚，
  回滚失败进入保护性降级。

## 测试

```powershell
python -m pytest -q --basetemp=.test_tmp
```

测试覆盖核心检测链路、API 集成、前端冒烟、规则生命周期、模型降级、
安全不变量与验收回归。CI（GitHub Actions）在 ubuntu/windows 矩阵上执行
安全扫描、全量测试、运行时验证与语法编译检查。

## 相关文档

- 运维手册：[docs/OPERATIONS.md](docs/OPERATIONS.md)
- 需求追溯：[docs/REQUIREMENT_TRACEABILITY.md](docs/REQUIREMENT_TRACEABILITY.md)
- 真实 LLM 配置示例：[config.real_llm.example.yaml](config.real_llm.example.yaml)
