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
