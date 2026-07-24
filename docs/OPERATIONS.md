# SafeChat-Guard Operations

## 安装与验证

```powershell
python -m pip install -r requirements.txt -r requirements-dev.txt
python scripts/security_scan.py
python -m pytest -q --basetemp=.test_tmp
python scripts/verify_runtime.py --iterations 20
python -m compileall app.py api_server.py safechat_guard scripts tests
```

运行验证报告默认写入 `.test_tmp/runtime_verification.json`，不会记录开发者本机
绝对路径，也不应提交缓存或临时报告。

## 启动

```powershell
python api_server.py
```

默认 `llm.provider=mock`，可离线运行。远程 OpenAI-compatible/Qwen 模式只从
`api_key_env` 指定的环境变量读取密钥，要求 HTTPS endpoint；未知 provider 会
启动失败，不会静默回退为 mock。远程服务失败时 `/api/chat` 返回安全 503，不
暴露上游正文或凭据。

启动后检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8000/ready
```

`/ready` 是运行时事实来源。语义模型、哈希、阈值与 `min_margin` 均由
`config/semantic_thresholds_v1.json` 管理；运维文档不得复制这些易过期值。

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
