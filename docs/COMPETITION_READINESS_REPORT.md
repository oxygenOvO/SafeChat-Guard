# SafeChat-Guard C 组赛前复核与改进报告

报告日期：2026-07-21  
工程版本：`competition-ready-v1`  
验收目录：`SafeChat-Guard-competition-ready`

## 1. 结论

当前工程已经达到“可安装、可启动、可演示、可联调、可回归”的比赛提交标准。输入过滤、输出复检、日志审计、健康检查、模型完整性校验、离线 Mock 和 Qwen 兼容调用链均已有实现与自动化测试。最终自动化结果为 `127 passed`，API 与 Streamlit 实际启动健康，12 条开发链路样例为 12/12。

但当前工程不能被描述为“已达到生产级检测效果”。char V2 模型的弱标签测试指标为：accuracy 53.85%、macro F1 48.77%、风险召回 61.36%、正常误报 14.29%。200 条独立候选仍全部处于 `pending`，系统正确拒绝生成正式 `semantic_gold_v1.csv`。因此，现阶段可以正式参加比赛并展示完整系统，不应宣称已经达到 80% 风险召回、5% 以下正常误报或正式比赛准确率。

## 2. 本轮重点问题

### 2.1 最可能被忽略的问题：并发日志竞争

后端使用 `ThreadingHTTPServer`，但旧 `EventLogger` 没有锁。并发请求可能在 `/api/chat` 写 JSONL 的同时由 `/api/stats` 读取，造成半行 JSON、解析异常或计数不一致。这一问题在单线程单元测试中很难暴露，却很容易在现场多人访问时出现。

解决方式：

- 写入、轮转、读取和统计共用进程内 `RLock`。
- 每条 JSONL 在锁内一次写入并刷新。
- 解析时容忍意外残留的损坏行，避免统计接口整体 500。
- 增加 200 次并发写入测试和 60 次并发 HTTP 请求测试。
- 增加 5 MiB 轮转、5 个备份、7 天保留策略。

扫描还发现测试会在工程目录留下 `.test_tmp/member_c_events.jsonl`。测试已改用 pytest 临时目录，污染文件已删除，并由交付扫描器永久拦截。

### 2.2 最没把握的问题：模型哈希是否真的形成安全门槛

旧实现只把 SHA-256 显示在配置和状态中，没有在加载前校验文件。这个做法既不能证明运行的就是交付模型，也不能阻止被替换的 joblib 文件进入反序列化。

查证结果：joblib 官方文档说明 `joblib.load()` 基于 pickle，加载不可信文件可能执行任意代码；Python 官方 pickle 文档也明确要求只反序列化可信数据。因此仅“记录哈希”不够，必须在 `joblib.load()` 之前验证制品。[joblib Persistence](https://joblib.readthedocs.io/en/stable/persistence.html)；[Python pickle](https://docs.python.org/3/library/pickle.html)

解决方式：

- 在反序列化前计算实际 SHA-256，并与配置值比较。
- 哈希不一致时不调用 `joblib.load()`，`/ready` 返回 503。
- 加载后验证 `predict_proba`、`classes_` 和预期类别集合。
- 状态接口同时返回 expected/actual SHA、完整性结果、类别契约和模型大小。
- 增加“哈希不一致时 joblib.load 从未被调用”的回归测试。
- 移除停用的旧 `semantic_model.pkl`，唯一活动模型为 `models/semantic_model_v2.joblib`。

## 3. 反馈问题逐项复核

| 反馈问题 | 状态 | 处理与证据 |
|---|---|---|
| C 分支范围过大 | 已控制 | 本轮保留模块边界，没有整库覆盖规则和训练数据；模型、API、日志、测试和文档均有独立文件职责。后续仍应按主题拆 PR。 |
| 大幅删除规则和词库 | 已解决 | 保留现有完整规则库，只补工程能力；未再替换词库。规则、归一化和对抗回归继续保留。 |
| 删除或弱化安全测试 | 已解决 | 未删除安全测试，新增模型供应链、日志并发、HTTP 并发、异常输入、Streamlit 启动和 Qwen 契约测试；最终 127 passed。 |
| `.gitignore` 和 CI 被削弱 | 已解决/待远端执行 | 恢复并扩展日志、缓存和模型忽略规则；CI 配置为 Windows/Linux 双平台、完整 pytest、运行验收、交付扫描和 compileall。远端 Actions 需上传后实际执行。 |
| 管道调用不存在的归一化接口 | 已解决 | 统一使用 `normalize_with_trace()`；现有归一化接口测试与全套测试通过。 |
| 非法类型、错误 JSON、超大请求导致崩溃 | 已解决 | 400/408/413/415/422/500 统一 JSON 错误；64 KiB 请求体、4096 字符、10 秒读取超时；异常详情不回传。 |
| 日志记录用户和模型原文 | 已解决 | 敏感字段递归替换为 `[REDACTED]`；增加并发锁、轮转、保留期、损坏行容错和敏感信息扫描。 |
| sanitize 返回未改变风险原文 | 已解决 | 未变化时安全重写，仍未变化则升级 block；输入输出两侧均验证，过滤时 `raw_reply=null`。 |
| 评估脚本覆盖输入动作 | 已解决 | 分别记录 `input_action`、`output_action` 和 `final_action`，报告分层统计。 |
| 原端到端效果 25% | 开发回归已解决 | 12 条开发样例达到 12/12；仅证明功能回归，不作为泛化或比赛准确率。 |
| 正式模型未接入 | 工程接入完成，模型效果待 B/A | 已接入可复现 char V2，SHA、类别、版本、参数和运行环境可追溯；它仍是弱标签模型，不是最终 gold 验收模型。 |
| API 契约不足 | 已解决 | `docs/API_CONTRACT.md` 覆盖请求、响应、限制、错误码、降级、`raw_reply`、stats、health/ready。 |
| 正式评估规模不足 | 未完成，外部阻塞 | 200 条候选仍 pending；未伪造 gold，未把 12/12 作为正式指标。需 A/B 完成人工复核与阈值校准。 |
| 可运维性不足 | 已解决 | health/ready、超时、并发测试、最大输入、日志轮转、统计时间窗、模型/配置版本均已实现。 |
| abuse 类别不统一 | 已明确边界 | `abuse` 暂由规则层处理，前端/日志/API 接受规则与语义类别并集；语义模型保持五分类，避免无数据扩类。 |
| Qwen 配置实际仍走 Mock | 已解决 | 新增 OpenAI 兼容 HTTPS 客户端、环境变量密钥、超时、503 安全失败；默认 Mock 保证离线演示。真实账号联网需比赛密钥。 |

## 4. 主要工程改进

1. 模型供应链：char V2 制品、清单、预加载 SHA 校验、类别契约、503 readiness。
2. HTTP：统一错误格式、请求体与字符限制、读取超时、内容类型检查、内部异常隐藏。
3. 可运维性：`/health`、`/ready`、`/api/stats?since=...`、版本与模型状态。
4. 日志安全：递归脱敏、并发锁、轮转、保留期、损坏行容错。
5. 大模型接入：离线 Mock 与 Qwen/OpenAI 兼容双模式，密钥只读环境变量。
6. 前端兼容：清理 Streamlit 废弃的 `use_container_width` 参数，增加 AppTest 启动测试。
7. 交付卫生：敏感凭据模式、大文件、缓存、临时日志自动扫描。
8. CI：Windows/Linux 双平台运行完整测试、运行验收、扫描和编译检查。

## 5. 最终测试结果

| 验收项 | 结果 |
|---|---|
| 全套 pytest | 127 passed，7.31 秒 |
| 模型加载 | loaded=true，error=null |
| 模型 SHA | expected 与 actual 均为 `0ce92d510692ed3ba5f55f0d1ac1a2cebd98b62c11139f22ee3ae5f11ed6f2e3` |
| 类别契约 | ad、normal、porn、sensitive、violence，校验通过 |
| 200 次本地完整链路 | 平均 1.65 ms，P95 1.88 ms，最大 2.35 ms |
| HTTP 并发 | 60 次并发聊天请求全部 200，事件计数准确 |
| JSONL 并发 | 200 次并发写入均为完整 JSON |
| 开发链路评估 | 12/12；输入、输出、最终动作分别统计 |
| Streamlit 自动启动 | 0 个页面异常 |
| 真机服务启动 | `/health=ok`、`/ready=true`、前端健康端点 200/ok |
| 安全扫描 | 无密钥模式、超大文件、缓存或临时日志 |
| Python 编译 | compileall 通过 |

## 6. 尚未完成与赛前动作

这些事项无法仅靠 C 组代码替代，应在答辩材料中如实标注：

1. A/B 完成 200 条独立样本双人审核，生成冻结的 `semantic_gold_v1.csv`。
2. B 只在 calibration 集校准阈值，并在独立 test 上运行一次最终评估。
3. 目标指标仍建议风险召回至少 80%、正常误报低于 5%；当前弱标签模型未达标。
4. 使用比赛 Qwen 账号完成一次真实联网联调；不得把密钥写入文件、截图或 Git。
5. 如果旧 Git 历史曾出现 API Key，必须在供应商控制台吊销、轮换并检查调用记录。当前工程扫描无凭据，但代码无法代替外部吊销。
6. 上传 GitHub 后确认 Windows/Linux 两个 Actions job 均通过。

## 7. 比赛使用建议

- 稳定演示：保持 `llm.provider=mock`，先展示输入归一化、规则+语义、分级处理、输出拦截和日志统计。
- 联网演示：改为 `qwen` 并设置 `QWEN_API_KEY`，启动前必须确认 `/ready` 为 200。
- 答辩表述：可以说“系统工程链路完整、127 项测试通过、模型制品可追溯”；不要说“12 条样例 100% 等于模型准确率 100%”。
- 提交前依次运行：`scripts/verify_runtime.py`、`scripts/security_scan.py`、`pytest -q`。

## 8. 交付物

- 完整工程：`SafeChat-Guard-competition-ready`
- 模型制品说明：`models/MODEL_MANIFEST.json`
- API 契约：`docs/API_CONTRACT.md`
- 运维说明：`docs/OPERATIONS.md`
- 机器可读运行验收：`reports/runtime_verification.json`
- 本报告：`docs/COMPETITION_READINESS_REPORT.md`
