# SafeChat-Guard Operations

本文所有命令均从项目根目录执行，不依赖开发者本机的绝对路径。

## 安装与验证

```powershell
python -m pip install -r requirements.txt -r requirements-dev.txt
python scripts/security_scan.py
python -m pytest -q --basetemp=.test_tmp
# 最终冻结 1286f3d 的干净 clone：594 collected；预期汇总为 594 passed
python scripts/verify_runtime.py --iterations 20
python -m compileall app.py api_server.py safechat_guard scripts tests
```

运行验证报告默认写入 `.test_tmp/runtime_verification.json`，不会记录开发者本机
绝对路径，也不应提交缓存或临时报告。

最终竞赛提交冻结版本为 `1286f3d`，干净 frozen clone 收集到 `594 collected`，实测 `594 passed, 1297 warnings in 79.27s`。`576 passed` 是 earlier/pre-final delivery baseline，不再是 final submission test count。测试应在干净 checkout/clone 中执行；若工作区含同名 untracked 测试副本，pytest 自动发现可能产生 collection error，此时不得用 `clean`、`stash -u` 或强制覆盖方式处理未确认的本地文件。

## 默认 mock 模式启动

```powershell
python api_server.py
```

默认 `config.yaml` 使用 `llm.provider=mock`，可离线运行且不会产生外部调用。NSCC Qwen3.5 模式必须显式选择 `config.real_llm.example.yaml`，API key 只从进程环境变量 `NSCC_MAAS_API_KEY` 读取；应用不从 YAML、`.env` 或命令行参数读取真实 key。真实模式要求 HTTPS endpoint；配置或远程服务失败时不静默回退为 mock，`/api/chat` 安全返回 503 且不暴露上游正文或凭据。

启动后检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8000/ready
```

`/ready` 是运行时事实来源。语义模型、哈希、阈值与 `min_margin` 均由
`config/semantic_thresholds_v1.json` 管理；运维文档不得复制这些易过期值。

## V3 能力边界

- V3 正式对抗归一化能力主要覆盖 Unicode/控制字符、符号插入、Emoji、同音、拼音、缩写、重复噪声及受控拆分恢复。
- `variant_char` 形近字扩展接口存在，但冻结版本的映射表为空，形近字恢复未正式启用；运维人员不得通过现场填充映射表改变冻结行为。
- 输入 sanitize 由 ActionRouterV3 判定。Sanitizer 对 normalized text 中已定位的 match 做局部改写，然后重新扫描、重新路由；无变化、失败、残余风险或复检异常时升级 block。它不是完整的结构化隐私字段正则系统。
- OutputGuard 是独立输出安全层，使用基础扫描 detection、自有 `block_threshold=80`、`sanitize_threshold=40`、privacy regex 和 extra high-risk rules。结构化隐私项包括 phone、email、id_card、bank_card、url、ip、wechat、qq、address。
- 核心训练/输入风险标签为 `normal/ad/porn/violence/sensitive`；OutputGuard 的 `privacy/illegal/self_harm` 等是输出运行时扩展类别，`abuse` 具有输出侧标签和安全响应支持。

## 日志

事件以 JSONL 写入本地 `data/logs/`。用户输入、模型原文、改写文本和规则匹配
会递归脱敏；并发写入由进程锁保护。大小轮转和 `retention_days` 是独立机制：
每次写入和读取都会清理过期备份，即使从未触发轮转也会生效。输入检测、输出
检测和最终动作分别记录，便于审计。

## 故障处理

- `/ready` 显示 LLM 未就绪：检查 endpoint、模型名与密钥环境变量是否存在，
  不要把密钥写入仓库。
- 可选语义模型缺失：规则层继续工作并报告降级；若配置为 required，服务不应
  宣告 ready。
- 模型完整性异常：恢复与正式配置哈希匹配的受信产物，不要修改配置去迁就来源
  不明的模型。
- 凭据曾进入 Git 历史：立即在提供方撤销并轮换；代码修改无法撤销外部凭据。

## 正式入口与兼容入口

`api_server.py` 是唯一正式HTTP API实现。`app.py` 仅为兼容启动包装器，直接复用正式服务器，不维护独立路由、Pipeline或请求校验。

从项目根目录启动正式入口：

```powershell
python api_server.py
```

如需兼容入口，同样从项目根目录执行 `python app.py`。配置相对于项目根目录解析；两个入口均提供相同的 `/health`、`/ready` 和 `/api/*` 行为。

每个持久化聊天请求结束后产生一条 `request_summary`。该摘要不包含完整输入或完整模型输出；日志写入失败只产生不含敏感原文的内部warning，不改变API安全结果。

## 规则管理运维

内置词表与正则保持只读；管理界面和 API 只写 `data/rules/user_rules.json`。写入流程为严格校验、同目录临时文件、fsync、单份 `.bak` 备份和原子替换。服务使用进程内写锁与 revision 乐观并发检查；更新成功后立即重载，其他进程会在下一次检测前按文件签名轻量重载。重载失败保留上一份已编译规则，不清空内置或内存规则。

生产环境必须设置管理员 token：

```powershell
$env:SAFECHAT_RULE_ADMIN_TOKEN = '<从密钥管理系统注入>'
python api_server.py
```

未设置 token 时，仅 loopback 客户端可执行规则写操作。不要把 token 写入配置、命令历史、日志或截图。CSV 必须为 UTF-8，规范表头为 `id,pattern,pattern_type,category,action,risk_level,enabled,description`；JSON 为规则数组或仅含 `rules` 的对象。建议先调用 validate-import 或在页面勾选 dry-run。

如果主 overlay 损坏，停止写操作并检查 `.bak`；不要用空数组覆盖损坏文件。恢复前验证 JSON 结构、revision 和 content_sha256。规则管理审计业务字段只记录 operation、rule_id、revision 和 result（日志基础层另加 stage/time），不记录 pattern、导入文件、token、异常堆栈或绝对路径。

## 每日统计

`/api/stats/summary` 和前端统计页只聚合 `request_summary`。日期边界按请求的 IANA timezone 计算；未指定时使用操作系统本地时区。空日志返回零值。损坏 JSONL 行会被跳过并产生不含正文和路径的 warning。旧日志缺少 request_summary 时明确标记 legacy，不能与请求数混用。
## User-rule transaction recovery

A rule mutation is successful only after disk persistence and RuleFilter activation agree on the same revision. Candidate compilation failure does not write the file. Activation failure rolls back the prior file and retains the last-good memory snapshot. Failed transactions emit a `stage=rule_management` audit event with `result=failed` and no pattern or exception text.

If rollback itself fails, rule management enters degraded mode: automatic rule reload is frozen on the last trusted snapshot and subsequent writes are rejected. Repair the user-rule storage from a trusted backup and restart the service before re-enabling management operations.

## 真实LLM运行手册

2026-07-31 已完成真实 Qwen 联网验证：provider=`qwen`、model=`qwen-plus`、status=`passed`，真实上游调用 2 次；pass 转发、block 不转发、sanitize 脱敏后转发、上游异常安全关闭、违规输出拦截五项均通过。验收输出满足 `credentials_printed=false`，运行后已清除进程环境变量 `DASHSCOPE_API_KEY`。其中上游异常与违规输出使用本地注入式安全路径测试，不代表 DashScope 发生过真实故障。以下步骤供获授权人员后续复验；仍须具备供应商账号、模型权限、网络和计费授权。

### 配置边界

- `config.yaml` 是默认离线配置，`llm.provider` 必须继续保持 `mock`。
- `config.real_llm.example.yaml` 是无密钥的真实上游示例。
- `SAFECHAT_CONFIG_PATH` 仅选择启动配置；未设置时API继续加载仓库根目录的 `config.yaml`。
- `NSCC_MAAS_API_KEY` 必须由进程环境或密钥管理平台注入。应用不会读取配置中的明文 key，也不会自动加载 `.env`。
- 真实配置缺失、provider未知、endpoint不是HTTPS或密钥未配置时不回退mock；`/ready` 降级或启动显式失败。

NSCC-CS MaaS OpenAI-compatible API 根地址为 `https://maas.nscc-cs.cn/external/api/v1`，客户端最终请求 `https://maas.nscc-cs.cn/external/api/v1/chat/completions`，模型 ID 为 `Qwen3.5`。

### 启动和检查

先通过部署平台注入 `NSCC_MAAS_API_KEY`，再执行：

```powershell
$env:NSCC_MAAS_API_KEY = "你的API_KEY"
$env:SAFECHAT_CONFIG_PATH = "config.real_llm.example.yaml"
python api_server.py
```

另开终端检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8000/ready
```

验收要点：`/health` 的V3模型状态保持ready且无fallback；`/ready` 的 `llm.ready=true`、provider和model符合配置。返回中只能出现 `key_configured` 布尔值，不能出现凭据。

### 冒烟脚本

```powershell
python scripts/smoke_real_llm.py --config config.real_llm.example.yaml
```

脚本只执行两次真实上游请求并验证五项安全性质：pass 转发、block 不转发、sanitize 后转发、上游异常安全失败、输出违规拦截。后两项通过本地受控客户端注入，不额外请求上游。脚本不打印输入、回复或密钥。运行可能产生供应商调用费用，必须由获授权人员执行。成功后还应重新检查 `/health` 和 `/ready`，并只留存不含 key、请求正文或模型回复的验收摘要。

### API调用示例

```powershell
$body = @{ message = "请给出一份一周阅读计划" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/chat -ContentType "application/json; charset=utf-8" -Body $body
```

不要在生产请求中使用 `raw_reply_override`；该兼容字段仅用于受控演示和测试。API出现 `service_error=llm_unavailable` 时按安全失败处理，不要绕过过滤器直接调用上游。

### 凭据和故障处置

- 不在工单、日志、截图或Git中粘贴key；`.env.example`只说明变量名。
- 怀疑泄漏时立即在供应商控制台撤销并轮换，再检查Git历史和CI日志。
- 401/403：检查key所属区域、模型权限和账户状态，不打印Authorization头。
- 连接超时：检查HTTPS出口、DNS和供应商状态；不得临时改为HTTP。
- 上游返回结构变化：客户端会返回安全503；先在隔离环境更新兼容性测试。
- 演示结束后由部署平台撤销临时凭据或关闭会话，不把key持久化到工作树。
