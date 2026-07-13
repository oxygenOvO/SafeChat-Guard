# SafeChat-Guard

SafeChat-Guard 是一个面向中文对话场景的大模型输入/输出安全防护系统，用于人工智能安全竞赛定向题目 1。系统围绕“输入侧违规识别、分级处理、大模型回复、输出侧二次校验、日志审计与可视化展示”构建，目标是在不从零训练大模型的前提下，为现有大模型提供一层可解释、可测试、可展示的内容安全守护模块。

当前版本已经形成可运行的工程原型：前端使用 Streamlit 展示完整安全链路，后端通过 `SafeChatPipeline` 串联中文对抗归一化、规则过滤、轻量语义分类、分级处理、Mock 大模型调用、输出复检和日志统计。项目保留了语义分类模型、训练数据、词库规则、测试用例和 API 联调接口，便于后续继续接入真实 Qwen/ChatGLM 等大模型服务。

## 功能原理

系统采用“规则检测 + 语义分类 + 分级处理 + 输出复检”的多层防护思路。

1. 输入归一化  
   用户输入首先经过中文对抗归一化模块，处理表情、谐音、拼音、缩写、变体字、大小写和噪声字符。例如 `V-X`、`薇信`、`优 惠 券` 会被归一化为更容易检测的标准表达。

2. 规则与词库检测  
   归一化文本进入关键词词库和正则规则层。词库覆盖广告引流、色情低俗、暴力威胁、敏感话术、辱骂低俗等类别；正则规则用于识别手机号、邮箱、链接等结构化风险内容。正则命中会返回真实命中值，便于脱敏和前端展示。

3. 轻量语义分类  
   系统使用 scikit-learn 训练的轻量文本分类器进行二次判断，类别包括 `normal`、`ad`、`porn`、`violence` 和 `sensitive`。语义层和规则层会同时运行并保留证据，避免只依赖关键词造成漏检或误判。

4. 分级处理  
   检测结果按照风险分数分为正常放行、中低风险安全改写、高风险拦截。中低风险文本会进入情感保留式改写模块，在尽量保留原始意图和情绪的基础上去除违规表达。

5. 输出侧二次校验  
   大模型回复也会经过同样的安全检查。若输出中包含广告、隐私信息、违法违规、高风险暴力或其他不合规内容，系统会进行脱敏、替换或拦截，防止模型回复产生二次风险。

6. 日志审计与统计展示  
   系统记录输入、输出、命中规则、风险类别、处理动作和最终回复，支持在前端进行统计展示和演示复盘。

## 系统流程

```text
用户输入
  -> 中文对抗归一化
  -> 关键词/正则规则检测
  -> 轻量语义分类
  -> 风险分级：放行 / 安全改写 / 拦截
  -> 大模型回复接口
  -> 输出侧二次校验
  -> 日志记录与统计展示
  -> Streamlit 前端演示
```

## 核心功能

- 输入侧过滤：支持词库、正则、中文对抗归一化后的违规内容检测。
- 语义二次判定：通过轻量文本分类模型识别疑似违规语义。
- 分级处理：高风险拦截，中低风险脱敏或情感保留式改写，正常内容放行。
- 输出侧校验：对模型回复再次检测，命中违规内容时进行拦截、脱敏或替换。
- 模型状态接口：可查看语义模型是否加载、模型类别和异常原因。
- API 联调接口：提供 `/api/chat`、`/api/detect`、`/api/stats`。
- 可视化展示：提供实时检测、基线对比、安全改写、输出复检、规则查看、批量评测和日志审计页面。
- 自动化测试：覆盖后端流程、规则命中、语义分类状态、输出校验、前端适配和 API 返回结构。

## 成员分工

| 成员 | 负责方向 | 当前完成内容 | 后续优化方向 |
| --- | --- | --- | --- |
| A 组 | 输入规则与词库 | 完成 `data/lexicons/` 基础词库、`data/rules/regex_rules.json` 正则规则、中文对抗归一化映射；规则层可以返回真实命中值 | 扩充高风险短句、误报白名单，完善词库增删改导入和持久化 |
| B 组 | 语义分类与风险分级 | 完成 `semantic_classifier.py`、训练脚本、训练数据、`models/semantic_model.pkl`；提供模型加载状态；新增 `/api/detect` 联调结构 | 扩大训练数据，校准阈值，补充正式评估指标，后续可替换更强分类模型 |
| C 组 | 输出校验、日志和后端流程 | 完成 `pipeline.py` 主流程、`output_guard.py` 输出复检、隐私脱敏、违规回复替换、`logger.py` 日志统计 | 将部分硬编码输出规则迁移到配置文件，完善统计图表和日志分析 |
| D 组 | 前端展示、测试和材料 | 完成 Streamlit 展示界面、前端适配层、批量评测、基线对比、日志审计和情感保留式改写展示 | 整理正式测试截图、项目报告、答辩 PPT 和演示脚本 |

## 目录结构

```text
main11/
├── app.py                         备用 Streamlit 单文件演示入口
├── api_server.py                  HTTP API 服务，提供 /api/chat、/api/detect、/api/stats
├── frontend/
│   ├── streamlit_app.py           主展示界面
│   └── adapter.py                 前端到后端安全链路的适配层
├── config.yaml                    阈值、模型方式和日志路径配置
├── requirements.txt               运行依赖
├── requirements-dev.txt           测试依赖
├── safechat_guard/
│   ├── pipeline.py                全链路统一入口
│   ├── normalizer.py              中文对抗归一化入口
│   ├── normalization/             模块化归一化框架
│   ├── rule_filter.py             词库和正则检测
│   ├── semantic_classifier.py     轻量语义分类器
│   ├── rewriter.py                情感保留式模板改写
│   ├── llm_client.py              大模型统一接口，目前为 Mock
│   ├── output_guard.py            输出侧复检和隐私脱敏
│   └── logger.py                  JSONL 日志与统计
├── data/
│   ├── lexicons/                  违规词库
│   ├── rules/                     正则规则
│   ├── maps/                      表情、谐音、拼音、缩写、变体字映射
│   ├── training_data/             语义模型训练数据
│   ├── test_cases/                前端批量评测样例
│   └── violation_sentences/       分类样本来源
├── models/semantic_model.pkl      已训练语义模型
├── docs/
│   └── SEMANTIC_CLASSIFIER_REPRODUCTION.md
├── scripts/                       数据准备和模型训练脚本
└── tests/                         自动化测试
```

## 安装与启动

建议使用 Python 3.11 或 3.12。

```powershell
cd "E:\信息安全yhy\LLM去毒化\人工智能安全竞赛\main11"
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run frontend\streamlit_app.py
```

如果已经使用比赛目录上一级的虚拟环境，可以直接运行：

```powershell
cd "E:\信息安全yhy\LLM去毒化\人工智能安全竞赛\main11"
..\.venv\Scripts\python.exe -m streamlit run frontend\streamlit_app.py
```

浏览器访问：

```text
http://127.0.0.1:8501
```

## API 联调

如需让其他成员或前端通过 HTTP 接口联调，可以启动 API 服务：

```powershell
cd "E:\信息安全yhy\LLM去毒化\人工智能安全竞赛\main11"
..\.venv\Scripts\python.exe api_server.py
```

接口示例：

- `POST http://127.0.0.1:8000/api/chat`  
  完整安全聊天链路，请求体：`{"message": "xxx"}`

- `POST http://127.0.0.1:8000/api/detect`  
  语义检测联调接口，请求体：`{"text": "xxx"}`

- `GET http://127.0.0.1:8000/api/stats`  
  日志统计和语义模型状态。

`/api/detect` 返回字段包括 `model_loaded`、`detections`、`model_error`、`normalized_text` 和 `semantic_scores`，前端可以按固定结构渲染。

## 运行测试

```powershell
cd "E:\信息安全yhy\LLM去毒化\人工智能安全竞赛\main11"
.\.venv\Scripts\python.exe -m pytest -q
```

当前自动化测试结果：

```text
26 passed
```

测试覆盖后端主流程、输出校验、归一化、前端适配、规则真实命中、语义模型状态和 `/api/detect` 返回结构。

## 模型训练

重新训练语义分类模型：

```powershell
.\.venv\Scripts\python.exe scripts\train_classifier.py
```

训练结果会覆盖 `models/semantic_model.pkl`，覆盖前建议备份原模型并记录评测结果。语义模型复现说明见 `docs/SEMANTIC_CLASSIFIER_REPRODUCTION.md`。

## 当前配置

- 风险阈值位于 `config.yaml` 的 `risk` 字段：默认 `80` 分拦截，`40` 分进入安全改写。
- 当前 `llm.provider` 为 `mock`，不会向互联网发送文本。
- Qwen/ChatGLM API 尚未真实接入，`QWEN_API_KEY` 只是环境变量占位。
- 后端日志默认保存在 `data/logs/events.jsonl`，该文件不会提交到 GitHub。
- 前端演示日志默认保存在 `outputs/`，该目录不会提交到 GitHub。

## 当前验证情况

- Streamlit 主界面可以正常加载。
- 语义模型可以加载，`/api/stats` 可查看模型状态。
- `V-X`、`薇信`、`优 惠 券` 等中文对抗表达可以被归一化。
- 手机号、邮箱、链接等正则命中会返回真实值并支持脱敏。
- 中低风险输入会进入情感保留式安全改写。
- 模拟违规模型输出可触发输出侧二次拦截。

以上结果属于当前工程原型验证，不等同于最终比赛指标。正式参赛前仍需使用更大规模测试集计算拦截率、误报率、分类指标和处理耗时。

## 后续待完善

1. 接入真实 Qwen/ChatGLM API，替换当前 Mock 大模型回复。
2. 完成词库和规则的前端增删改、批量导入和持久化保存。
3. 扩充高风险短句、中文对抗样本和误报白名单。
4. 重新校准语义分类阈值，补充正式评测集。
5. 将输出侧部分硬编码规则迁移到配置文件。
6. 整理项目报告、测试截图、答辩 PPT 和最终提交材料。
