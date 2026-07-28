# SafeChat-Guard API Contract

本文定义 `api_server.py` 的稳定 HTTP 接口。运行时以
`config/semantic_thresholds_v1.json` 为唯一正式语义配置来源；本文不固化阈值、
模型哈希或模型版本，具体状态以 `/ready` 返回为准。

## 通用约束

- POST 请求体最大 64 KiB（可由 `config.yaml` 调整）。
- `message`、`text`、`raw_reply_override` 每字段最多 4096 字符。
- POST 请求体必须为 JSON 对象；文本字段必须是非空字符串。
- 错误统一为 `{"error": "code", "message": "safe message"}`，不返回异常细节、
  上游响应或用户原文。
- 语义模型为可选时，模型缺失会明确标记为降级，规则检测仍继续运行。

## GET /health

仅表示 HTTP 进程存活，返回 `status` 与 `service`。

## GET /ready

返回 `ready`、`semantic_classifier`、`llm` 与 `stats`。配置为必需的语义模型
不可用，或 LLM provider 未就绪时，HTTP 状态为 503；可选语义模型缺失时允许
规则层安全降级。响应中的路径均为项目相对路径或文件名。

## GET /api/stats

返回事件数、输入/输出/最终动作计数、规则/语义命中数和分类器/LLM 状态。
可使用 `since=<ISO-8601>` 过滤时间窗口；无效时间返回 422。

## POST /api/detect

请求：`{"text": "待检测文本"}`。

该接口执行与输入流水线相同的归一化、规则检测和语义检测，并返回联合的
`detections`、`action`、`risk_score`、`risk_level`、`risk_categories` 以及语义模型
状态。它不是 semantic-only 接口。

## POST /api/chat

请求：`{"message": "用户消息"}`。`raw_reply_override` 仅用于可控的输出防护
验证，但仍经过完整输出复检。

- 输入 block：不调用 LLM，`raw_reply=null`。
- LLM 不可用：HTTP 503，`service_error=llm_unavailable`，`raw_reply=null`。
- 输出 sanitize 或 block：`raw_reply=null`，不向调用方返回未过滤模型原文。
- 输入和输出改写后都重新执行归一化、规则检测和语义检测；复检仍有风险则
  block。

## 状态码

- 400：JSON、编码或 Content-Length 无效。
- 408：读取请求体超时。
- 413：请求体或文本字段超限。
- 415：Content-Type 不是 JSON。
- 422：字段缺失或类型不正确。
- 404：接口不存在。
- 500：内部错误（统一安全响应）。
- 503：LLM 或必需运行依赖不可用。

## 最终动作字段

`POST /api/chat` 的动作字段定义如下：

- `action`：输入侧动作，保留用于向后兼容。
- `allowed`：旧兼容布尔字段。
- `final_action`：整个请求完成输入过滤和输出复检后的最终动作。
- `final_allowed`：推荐客户端用于最终判断的布尔字段。
- `input_filter.action`：输入过滤动作。
- `output_filter.action` 或 `output_guard_action`：输出检查动作；未执行时为 `null` 或 `not_run`。

外部客户端必须优先检查 `final_allowed` 和 `final_action`，不得只依据 `action` 判断最终结果。

### 映射规则

- 输入直接拦截：`action=block`、`final_action=block`、`final_allowed=false`。
- 输入放行且输出安全：`final_action=pass`、`final_allowed=true`。
- 输入脱敏成功且输出安全：`final_action=sanitize`、`final_allowed=true`。
- OutputGuard拦截输出：`final_action=block`、`final_allowed=false`。
- 服务异常或fail-closed：`final_action=block`、`final_allowed=false`。

OutputGuard拦截时，`raw_reply` 必须为 `null`，`model_response` 不得包含违规原始模型输出，`reply` 只包含标准安全替换文本。

## 请求级审计摘要

每个持久化聊天请求完成后写入且仅写入一条 `request_summary`。摘要包含输入、输出和最终动作、类别、风险、真实模型转发状态、sanitize状态、fallback状态、语义模型状态及端到端延迟。

审计摘要不保存完整用户输入或完整模型输出。日志写入失败不得改变已经完成的安全响应，也不得向API客户端暴露异常正文、路径或敏感文本。
