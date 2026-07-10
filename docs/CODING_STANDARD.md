# SafeChat-Guard 编码规范

## 1. Python 编码规范

- 使用 Python 3.11+ 语法风格，优先保持代码简单清晰。
- 文件名、函数名、变量名使用小写加下划线，例如 `semantic_classifier.py`、`risk_score`。
- 类名使用大驼峰，例如 `SemanticClassifier`、`RuleFilter`。
- 每个模块只负责一类职责：
  - `normalizer.py` 负责文本归一化入口。
  - `rule_filter.py` 负责关键词和正则规则检测。
  - `semantic_classifier.py` 负责语义层风险判断。
  - `sanitizer.py` 负责脱敏处理。
  - `pipeline.py` 负责串联完整流程。
- 检测模块统一返回 `Detection` 对象，不要返回临时字典。
- 不要在核心模块里直接写演示用输出；演示展示应放在前端或文档中。
- 新增逻辑时优先写小函数，避免把大量判断堆在一个函数里。

## 2. 项目目录规范

```text
SafeChat-Guard/
  app.py                         # Web 服务入口
  config.yaml                    # 项目配置，当前内容为 JSON 兼容格式
  data/
    lexicons/                    # 四类词库
    maps/                        # 归一化映射表
    rules/                       # 正则规则
    test_cases/                  # 测试样例
    logs/                        # 运行日志
  docs/                          # 项目文档
  safechat_guard/                # 核心代码
  tests/                         # 自动化测试
```

- 词库文件放在 `data/lexicons/`，一行一个词或短句。
- 归一化映射放在 `data/maps/`，使用 JSON 对象。
- 正则规则放在 `data/rules/regex_rules.json`。
- 测试样例放在 `data/test_cases/sample_cases.jsonl`。
- 不要把临时脚本、截图、压缩包放进核心代码目录。

## 3. JSON 文件规范

- 所有 JSON 文件必须是合法 JSON，不能有注释、尾随逗号或重复键。
- 正则表达式中的反斜杠必须转义，例如：

```json
{
  "pattern": "1[3-9]\\d{9}"
}
```

- 归一化映射表推荐使用增强格式：

```json
{
  "加薇": {
    "target": "加微信",
    "type": "homophone",
    "category_hint": "ad",
    "confidence": 0.95
  }
}
```

- `target` 是程序实际使用的归一化结果。
- `type` 表示归一化类型，例如 `emoji`、`homophone`、`abbreviation`、`pinyin`。
- `category_hint` 表示可能关联的风险类别，例如 `ad`、`porn`、`violence`、`sensitive`。
- `confidence` 范围为 0 到 1。
- 如果一个符号有多个含义，只能选择一个主 `target`；其他含义可放在 `aliases` 中作为备注。

## 4. UTF-8 编码要求

- 所有源码、词库、JSON、Markdown、JSONL 文件必须使用 UTF-8 编码。
- 不要使用 ANSI、GBK 或复制后产生乱码的内容。
- 中文内容写入后要重新打开检查，确认没有出现连续问号乱码。
- Windows 上编辑时建议使用 VS Code，并确认右下角编码显示为 `UTF-8`。
- 如果发现文件已经乱码，不要继续在乱码基础上修补，应直接重建内容。

## 5. 测试规范

- 每新增一个过滤能力，都要补充至少一条测试样例。
- `tests/` 中的测试应使用真实中文输入，不允许使用乱码或无意义问号。
- `sample_cases.jsonl` 中每行是一条 JSON，至少包含：

```json
{"id":"ad_001","category":"ad","text":"想领取课程资料可以加微信私聊。","expected":"sanitize"}
```

- `expected` 推荐值：
  - `pass`：正常放行。
  - `sanitize`：中风险脱敏。
  - `block`：高风险拦截。
- 测试集应覆盖正常文本、广告引流、色情低俗、暴力威胁、敏感内容五类。
- 提交前至少确认：
  - 正常文本不会被误拦截。
  - 广告引流文本会被脱敏或拦截。
  - 色情低俗和暴力威胁文本会被拦截。
  - 敏感内容会被标记并进入分级处理。
