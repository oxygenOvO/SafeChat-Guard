# SafeChat-Guard

SafeChat-Guard 是一个面向中文对话场景的大模型输入/输出安全防护系统，用于人工智能安全竞赛定向题目 1。系统围绕“输入侧违规识别、分级处理、大模型回复、输出侧二次校验、日志审计与可视化展示”构建，目标是在不从零训练大模型的前提下，为现有大模型提供一层可解释、可测试、可展示的内容安全守护模块。

当前版本已经形成可运行、可联调、可复现评测的工程原型：前端使用 Streamlit 展示完整安全链路，后端通过 `SafeChatPipeline` 串联中文对抗归一化、规则过滤、轻量语义分类、分级处理、大模型调用、输出复检和脱敏日志统计。默认使用离线 Mock 保证演示稳定，也支持通过环境变量接入 Qwen 的 OpenAI 兼容 HTTPS 接口。

## 功能原理

系统采用“规则检测 + 语义分类 + 分级处理 + 输出复检”的多层防护思路。

1. 输入归一化  
   用户输入首先经过中文对抗归一化模块，处理表情、谐音、拼音、缩写、变体字、大小写和噪声字符。例如 `V-X`、`薇信`、`优 惠 券` 会被归一化为更容易检测的标准表达。

2. 规则与词库检测  
   归一化文本进入关键词词库和正则规则层。词库覆盖广告引流、色情低俗、暴力威胁、敏感话术、辱骂低俗等类别；正则规则用于识别手机号、邮箱、链接等结构化风险内容。正则命中会返回真实命中值，便于脱敏和前端展示。对于“网络”“谣言”等易误判弱词，后端只在安全防护、课程实验、识别治理等明确中性语境下抑制单一命中，其他组合风险仍正常处理。

3. 轻量语义分类  
   系统使用 scikit-learn 训练的轻量文本分类器进行二次判断，类别包括 `normal`、`ad`、`porn`、`violence` 和 `sensitive`。语义层和规则层会同时运行并保留证据，各类别阈值可在 `config.yaml` 中单独校准；模型缺失或加载失败时会显式降级到规则层并返回状态，而不是静默伪装为已加载。

4. 分级处理  
   检测结果按照风险分数分为正常放行、中低风险安全改写、高风险拦截。中低风险文本会进入情感保留式改写模块，在尽量保留原始意图和情绪的基础上去除违规表达。

5. 输出侧二次校验  
   大模型回复也会经过同样的安全检查。若输出中包含广告、隐私信息、违法违规、高风险暴力或其他不合规内容，系统会进行脱敏、替换或拦截，防止模型回复产生二次风险。

6. 日志审计与统计展示  
   系统记录命中规则、风险类别、处理动作和统计信息，写入前会对输入、模型原始回复和最终回复中的敏感信息进行脱敏，支持在前端进行统计展示和演示复盘。

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
- API 联调接口：提供 `/api/chat`、`/api/detect`、`/api/stats`、`/health`、`/ready`。
- 可视化展示：提供实时检测、基线对比、安全改写、输出复检、规则查看、批量评测和日志审计页面。
- 数据与评测：提供训练数据审计、中文对抗集构建、重复/泄漏候选检查、双人复核模板和独立 gold 集生成流程。
- 工程安全：限制请求大小、文本长度和读取超时；模型在反序列化前校验 SHA-256 和类别契约；不向前端返回被过滤的原始模型输出；日志落盘前统一脱敏并支持并发安全轮转。
- 自动化测试与 CI：覆盖后端流程、配置阈值、规则命中、归一化、模型降级、输出校验、数据构建和 API 返回结构，并通过 GitHub Actions 持续验证。

## 成员分工

| 成员 | 负责方向 | 当前完成内容 | 后续优化方向 |
| --- | --- | --- | --- |
| A 组 | 输入规则、词库与数据基线 | 完成基础词库、正则规则、中文对抗归一化映射、符号变体映射、训练数据审计和多版本对抗评测集构建；规则层可返回真实命中值 | 扩充真实攻击样本，继续人工核验映射置信度、误报边界和数据来源 |
| B 组 | 语义分类与风险分级 | 完成轻量语义分类器、训练数据和模型加载状态接口；补充可复现的 Word/Char 基线 V2、分类阈值配置和模型降级处理 | 完成独立人工 gold 评测，基于正式验证集校准阈值，再考虑接入更强分类模型 |
| C 组 | 输出校验、日志和后端流程 | 完成统一 Pipeline、输出复检、隐私脱敏、违规回复替换、细分日志统计；补充 API 输入校验、请求大小限制和原始违规输出保护 | 将更多输出策略迁移到配置文件，完善性能统计与并发压测 |
| D 组 | 前端展示、测试和材料 | 完成 Streamlit 展示界面、前端适配层、批量评测、基线对比、日志审计和情感保留式改写展示；整理内部链路测试用例 | 后续单独优化参赛界面、正式测试截图、项目报告、答辩 PPT 和演示脚本 |

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
│   ├── evaluation/                基线、对抗与独立评测候选集
│   ├── test_cases/                前端批量评测样例
│   └── violation_sentences/       分类样本来源
├── models/
│   ├── semantic_model_v2.joblib   当前 char n-gram 语义模型
│   └── MODEL_MANIFEST.json        模型哈希、类别、版本和训练环境
├── docs/
│   ├── DATA_BASELINE_V1.md         数据审计与对抗评测说明
│   ├── ANNOTATION_GUIDELINES_V1.md 人工标注规范
│   ├── SEMANTIC_BASELINE_V2.md     可复现语义基线说明
│   ├── API_CONTRACT.md             HTTP 接口契约
│   ├── OPERATIONS.md               比赛启动与运维说明
│   ├── COMPETITION_READINESS_REPORT.md 详细赛前复核报告
│   └── SafeChat-Guard_C组赛前复核与改进报告.docx 正式 Word 报告
├── reports/                       数据审计、人工复核和模型实验记录
├── scripts/                       数据准备、训练、审计和评测脚本
└── tests/                         自动化测试
```

## 安装与启动

比赛交付包建议使用 Python 3.14；依赖版本已固定，并与模型制品清单一致。

```powershell
cd "SafeChat-Guard-competition-ready"
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run frontend\streamlit_app.py
```

浏览器访问：

```text
http://127.0.0.1:8501
```

## API 联调

如需让其他成员或前端通过 HTTP 接口联调，可以启动 API 服务：

```powershell
cd "SafeChat-Guard-competition-ready"
.\.venv\Scripts\python.exe api_server.py
```

接口示例：

- `POST http://127.0.0.1:8000/api/chat`  
  完整安全聊天链路，请求体：`{"message": "xxx"}`

- `POST http://127.0.0.1:8000/api/detect`  
  语义检测联调接口，请求体：`{"text": "xxx"}`

- `GET http://127.0.0.1:8000/api/stats`  
  日志统计和语义模型状态。

- `GET http://127.0.0.1:8000/health`  
  进程存活检查。

- `GET http://127.0.0.1:8000/ready`  
  模型加载、哈希和类别契约验收；不满足时返回 `503`。

`/api/detect` 返回字段包括 `model_loaded`、`detections`、`model_error`、`normalized_text` 和 `semantic_scores`，前端可以按固定结构渲染。

## 运行测试

```powershell
cd "SafeChat-Guard-competition-ready"
.\.venv\Scripts\python.exe -m pytest -q
```

比赛前一键验收：

```powershell
.\.venv\Scripts\python.exe scripts\verify_runtime.py
.\.venv\Scripts\python.exe scripts\security_scan.py
```

当前自动化测试结果（2026-07-21）：

```text
127 passed
```

测试覆盖后端主流程、输出校验、归一化、前端适配、配置阈值、规则真实命中、模型降级与完整性、日志脱敏与并发轮转、HTTP 并发、Qwen 兼容契约、Streamlit 启动、数据审计和独立评测流程。

## 模型训练

重新训练语义分类模型：

```powershell
.\.venv\Scripts\python.exe scripts\train_classifier.py
```

旧版 `scripts/train_classifier.py` 只用于复现实验，不应覆盖当前比赛模型。当前模型由 V2 流程生成，唯一运行路径为 `models/semantic_model_v2.joblib`，制品信息见 `models/MODEL_MANIFEST.json`。

语义基线 V2 使用固定分组拆分比较 Word/Char TF-IDF 模型，模型选择仅依据 validation，测试结果不参与选型：

```powershell
..\.venv\Scripts\python.exe scripts\prepare_semantic_data_v2.py
..\.venv\Scripts\python.exe scripts\train_semantic_baseline_v2.py
..\.venv\Scripts\python.exe scripts\evaluate_semantic_baseline_v2.py
```

V2 指标仅针对当前弱标签分组留出集，不是正式比赛成绩。完整限制和复现说明见 `docs/SEMANTIC_BASELINE_V2.md`。

## 数据审计与独立评测

当前仓库已生成 200 条语义独立评测候选及双人复核模板，但候选仍需人工审核，不能直接作为正式 gold 集或比赛指标。推荐流程：

```powershell
..\.venv\Scripts\python.exe scripts\audit_training_data.py --input data\training_data\raw_train_v3.csv --report-dir reports\data_audit_v1
..\.venv\Scripts\python.exe scripts\build_evaluation_sets.py --output-dir data\evaluation --report-dir reports\data_audit_v1
..\.venv\Scripts\python.exe scripts\build_independent_eval_v1_candidates.py
..\.venv\Scripts\python.exe scripts\audit_independent_eval_v1.py
```

两名成员按 `docs/ANNOTATION_GUIDELINES_V1.md` 独立复核 `reports/manual_review/semantic_independent_eval_v1_review_template.csv`。全部样本处理为 `verified` 或 `rejected` 并填写复核人后，再运行：

```powershell
..\.venv\Scripts\python.exe scripts\build_semantic_gold_v1.py
..\.venv\Scripts\python.exe scripts\evaluate_system_v1.py --mode combined
```

脚本会拒绝包含 `pending` 状态的复核表，避免误把自动候选当作正式测试集。

## 当前配置

- 风险阈值位于 `config.yaml` 的 `risk` 字段：默认 `80` 分拦截，`40` 分进入安全改写。
- 各语义类别置信度阈值位于 `config.yaml` 的 `semantic_thresholds` 字段，配置非法时启动会明确报错。
- 当前 `llm.provider` 默认为 `mock`，不会向互联网发送文本。
- 将 provider 改为 `qwen`、配置 HTTPS chat-completions 地址并设置 `QWEN_API_KEY` 后，可调用真实 Qwen 兼容接口；密钥不写入配置和日志，远端失败会安全返回 `503`。
- 后端日志默认保存在 `data/logs/events.jsonl`，敏感字段写入前会脱敏；默认 5 MiB 轮转、保留 5 个备份和 7 天，该文件不会提交到 GitHub。
- 前端演示日志默认保存在 `outputs/`，该目录不会提交到 GitHub。

## 当前验证情况

- Streamlit 主界面可以正常加载。
- char V2 语义模型可以加载，`/ready` 会同时校验 SHA-256 和类别集合，`/api/stats` 可查看非敏感状态。
- `V-X`、`薇信`、`优 惠 券` 等中文对抗表达可以被归一化。
- 手机号、邮箱、链接等正则命中会返回真实值并支持脱敏。
- 中低风险输入会进入情感保留式安全改写。
- 模拟违规模型输出可触发输出侧二次拦截。
- 内部 12 条开发链路样例当前为 12/12，通过项覆盖正常放行、对抗归一化、中风险改写、高风险拦截和输出侧拦截。
- 当前完整自动化测试为 127 项，并配置 GitHub Actions 在 Windows/Linux 上运行测试、运行验收、安全扫描与 Python 编译检查。

以上结果属于当前工程原型的回归验证，样例规模小且参与了开发，不等同于最终比赛指标。正式参赛前仍需在人工确认、与训练来源隔离的独立测试集上计算拦截率、误报率、分类指标和处理耗时。

## 后续待完善

1. 完成 200 条独立评测候选的双人复核，生成不含数据泄漏的正式 gold 集。
2. 扩充有来源依据的真实攻击样本和高风险短句，继续核验中文对抗映射及误报边界。
3. 在独立验证集上重新校准语义分类阈值，报告分类指标、误报率和对抗鲁棒性。
4. 将输出侧部分硬编码规则迁移到配置文件。
5. 补充真实 Qwen 账号下的联网联调截图与调用成本记录。
