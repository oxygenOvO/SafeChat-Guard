# SafeChat-Guard 四人分工融合增强版

本目录是 2026 第二届大学生人工智能安全竞赛定向题目 1 的融合工程。当前版本以 `main11` 为底座，保留语义模型、训练数据和情感保留式改写，同时吸收远程仓库更新中的新版 Streamlit 前端、模块化中文对抗归一化、更多映射表、B 组语义状态接口和 `/api/detect` 联调接口。

当前主流程：

```text
用户输入
  -> 模块化中文对抗归一化
  -> 关键词/正则规则检测（成员 A）
  -> 轻量语义分类（成员 B，和规则层并行保留证据）
  -> 高风险拦截 / 中低风险安全改写 / 正常放行
  -> Mock 大模型回复（成员 B 预留接口）
  -> 输出复检、隐私脱敏和合规替换（成员 C）
  -> JSONL 日志、统计和模型状态暴露（成员 C/B）
  -> 新版 Streamlit 展示、批量评测和报告素材（成员 D）
```

## 一、四人分工完成情况

| 成员 | 负责方向 | 当前已完成内容 | 后续仍需补充 |
| --- | --- | --- | --- |
| A 组：输入规则与词库 | 输入侧过滤、词库、正则、中文对抗归一化 | 已整理 `data/lexicons/` 四类基础词库和 `data/rules/regex_rules.json`；已接入表情、谐音、拼音、缩写、变体字等归一化映射；规则层可以输出真实命中值，便于脱敏和展示 | 继续补高风险短句、误报白名单、词库增删改导入和持久化 |
| B 组：语义分类与分级 | 轻量语义分类模型、模型状态、联调接口 | 已提供 `semantic_classifier.py`、`models/semantic_model.pkl`、训练脚本和训练数据；已增加 `status()`，可返回模型是否加载、类别和错误；规则层与语义层现在会同时运行并保留证据；新增 `/api/detect` 语义联调接口 | 继续扩大训练数据，校准阈值，补正式评估指标；如时间允许替换为更强模型 |
| C 组：输出校验、日志和后端流程 | 输出侧复检、隐私脱敏、日志统计、主流程 | 已完成 `pipeline.py` 串联输入过滤、语义分类、分级处理、Mock LLM、输出复检和日志；`output_guard.py` 支持输出侧违规拦截、隐私信息脱敏和高风险回复替换；`logger.py` 提供 JSONL 日志和统计 | 输出高风险规则仍有部分硬编码，后续可迁移到配置；需要补更完整的日志统计图表 |
| D 组：前端展示、测试和材料 | Streamlit 展示、批量评测、报告素材 | 已完成新版 `frontend/streamlit_app.py`，包含实时检测、基线对比、安全改写、输出复检、规则查看、批量评测和日志审计；前端已接真实 `SafeChatPipeline`；情感保留式改写已保留在 `rewriter.py` | 继续整理正式测试截图、项目报告、PPT 和老师审查材料 |

## 二、融合来源

| 模块 | 采用内容 | 来源 |
| --- | --- | --- |
| 输入规则层 | `normalizer.py`、`normalization/`、`rule_filter.py`、规则配置和新版映射文件 | 分工 1 + 临时仓库更新 |
| 语义分类层 | `semantic_classifier.py`、训练脚本、训练数据、`semantic_model.pkl`、模型状态和 `/api/detect` | 分工 2 + 远程分支更新 |
| 输出与日志层 | `output_guard.py`、`logger.py`、输出处理主流程 | 分工 3 |
| 展示与测试层 | `frontend/streamlit_app.py`、`frontend/adapter.py`、`test_cases_sample.csv`、基线对比、情感保留式改写、批量样例 | 分工 4 + 临时仓库更新 |

本次增强没有覆盖 `models/semantic_model.pkl`、`data/training_data/` 和 `safechat_guard/rewriter.py`。也就是说，远程仓库的前端、归一化、语义状态和接口改进被吸收进来，但 `main11` 中更完整的模型、训练数据和情感保留式改写仍然保留。

## 三、目录说明

```text
main11/
├── app.py                         原单文件 Streamlit 主界面，可作为备用演示入口
├── api_server.py                  独立 HTTP API，提供 /api/chat、/api/detect、/api/stats
├── frontend/
│   ├── streamlit_app.py           新版比赛展示控制台
│   └── adapter.py                 前端到真实安全链路的适配层
├── config.yaml                    阈值、模型方式和日志路径配置（内容为 JSON 语法）
├── requirements.txt               Python 依赖
├── test_cases_sample.csv          前端批量评测样例
├── safechat_guard/
│   ├── pipeline.py                全链路统一入口
│   ├── normalizer.py              中文变体归一化
│   ├── normalization/             模块化归一化框架
│   ├── rule_filter.py             词库和正则检测
│   ├── semantic_classifier.py     轻量语义分类
│   ├── rewriter.py                情感保留式模板改写
│   ├── llm_client.py              大模型统一接口，目前为 Mock
│   ├── output_guard.py            输出复检和隐私脱敏
│   └── logger.py                  JSONL 日志与统计
├── data/
│   ├── lexicons/                  违规词库
│   ├── rules/                     正则规则
│   ├── maps/                      表情、谐音、拼音、缩写、变体字映射
│   ├── test_cases/                新版前端批量评测样例
│   ├── training_data/             语义模型训练数据
│   └── violation_sentences/       分类样本来源
├── models/semantic_model.pkl      已训练语义模型
├── docs/
│   └── SEMANTIC_CLASSIFIER_REPRODUCTION.md  B 组语义模型复现实验说明
├── scripts/                       数据准备和模型训练脚本
└── tests/                         后端流程与输出校验测试
```

## 四、安装与启动

建议使用 Python 3.11 或 3.12。在 PowerShell 中执行：

```powershell
cd "E:\信息安全yhy\LLM去毒化\人工智能安全竞赛\main11"
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run frontend\streamlit_app.py
```

终端出现地址后，在浏览器打开 `http://localhost:8501`。停止服务时在终端按 `Ctrl+C`。

如果已经使用比赛目录上一级的现有虚拟环境，也可以这样启动：

```powershell
cd "E:\信息安全yhy\LLM去毒化\人工智能安全竞赛\main11"
..\.venv\Scripts\python.exe -m streamlit run frontend\streamlit_app.py
```

旧版单文件页面仍可运行：

```powershell
..\.venv\Scripts\python.exe -m streamlit run app.py
```

如需让前端或其他同学通过 HTTP 接口联调，可以单独启动 API 服务：

```powershell
cd "E:\信息安全yhy\LLM去毒化\人工智能安全竞赛\main11"
..\.venv\Scripts\python.exe api_server.py
```

接口地址：

- `POST http://127.0.0.1:8000/api/chat`：完整安全聊天链路，请求体 `{"message": "xxx"}`
- `POST http://127.0.0.1:8000/api/detect`：B 组语义检测联调，请求体 `{"text": "xxx"}`
- `GET http://127.0.0.1:8000/api/stats`：日志统计和语义模型加载状态

`/api/detect` 会返回固定结构，包含 `model_loaded`、`detections`、`model_error`、`normalized_text` 和 `semantic_scores`，前端可以先按这个结构完成渲染。

## 五、界面使用顺序

1. 在“实时检测工作台”输入文本，查看归一化、规则检测、语义分类、分级处理、模型回复和输出复检的完整链路。
2. 勾选“模拟大模型输出违规内容”，验证输出侧二次拦截。
3. 在“基线对比”查看未归一化规则与增强流程的差异。
4. 在“安全改写”查看中低风险文本的改写结果。
5. 在“批量评测”上传 `test_cases_sample.csv`，或使用 `data/test_cases/frontend_cases.csv` 中的新版内置样例。
6. 点击“记录到日志”后，在“日志审计”查看和导出本次演示记录。

后端也可以单独调用：

```python
from safechat_guard.pipeline import SafeChatPipeline

pipeline = SafeChatPipeline.from_config("config.yaml")
result = pipeline.handle_chat("今天图书馆几点关门？")
print(result["reply"])
print(result["input_filter"])
print(result["output_filter"])
```

## 六、运行测试

```powershell
cd "E:\信息安全yhy\LLM去毒化\人工智能安全竞赛\main11"
.\.venv\Scripts\python.exe -m pytest -q
```

重新训练成员 B 的语义分类模型：

```powershell
.\.venv\Scripts\python.exe scripts\train_classifier.py
```

训练结果会覆盖 `models/semantic_model.pkl`，覆盖前建议备份原模型并记录评测结果。

## 七、配置与日志

- 风险阈值在 `config.yaml` 的 `risk` 字段中设置：默认 `80` 分拦截，`40` 分进入安全改写。
- 当前 `llm.provider` 为 `mock`，因此不需要 API Key，也不会向互联网发送文本。Qwen API 仍未真实接入。
- 持久化后端日志位于 `data/logs/events.jsonl`。
- 前端手动记录的展示日志位于 `outputs/demo_logs.csv`。
- 模型文件和训练数据属于比赛交付物，当前工程特意没有在 `.gitignore` 中排除它们。
- 语义模型状态可以通过 `pipeline.stats()["semantic_classifier"]` 或 `/api/stats` 查看。

## 八、本次融合验证结果

- 自动化测试：`26 passed`，覆盖后端流程、输出校验、归一化、前端适配、规则真实命中、语义模型状态和 `/api/detect` 返回结构。
- 新版 Streamlit 应用测试：`frontend/streamlit_app.py` 可加载，页面异常数为 `0`。
- 关键链路：语义模型可以加载；规则层和语义层可以同时保留证据；手机号等正则命中会返回真实值并被脱敏；`V-X/优 惠 券` 可归一化为 `微信/优惠券` 并进入安全改写；中低风险输入会调用情感保留式改写；模拟违规模型输出可二次拦截。
- 内置 12 条初版样例：处理匹配率 `75%`、输出校验匹配率 `100%`、违规处理率 `100%`、正常样例误判率 `50%`。

以上仅是融合后的冒烟测试，不是正式比赛指标。尤其是误判率明显未达到赛题要求，不能直接写入最终作品报告作为有效成绩。

## 九、目前仍需完善

这些内容没有在本次融合中补写，建议团队后续按优先级继续完成：

1. **接入真实开源大模型 API**：`safechat_guard/llm_client.py` 目前无论配置什么 provider 都返回 Mock；这是距离赛题“对接 Qwen/ChatGLM API”最大的缺口。
2. **完成词库管理闭环**：前端现在只能在当前会话临时添加词条，还缺删除、批量导入和保存回词库文件。
3. **补高风险短句和误报白名单**：例如暴力威胁、爆炸物制作等短句需要继续补规则和测试；正常安全研究语境也要防止误杀。
4. **继续扩充中文对抗映射**：本版已经吸收表情、谐音、拼音、缩写、变体字映射，但覆盖率还需要用正式测试集继续补。
5. **重新校准测试用例和语义阈值**：`test_cases_sample.csv` 是成员 D 按演示逻辑编写的初版预期值，融合真实分类模型后部分结果可能变化。当前模型对训练词表外文本的概率区分度较低，需要逐条复核标签、阈值和误判样例。
6. **完成比赛指标验证**：扩大正常与违规测试集，正式计算明显违规拦截率、正常文本误判率、分类指标和处理耗时，验证是否达到拦截率不低于 90%、误判率不高于 5%。
7. **优化安全改写**：当前为规则和模板改写，不是真正的生成式安全改写器；五维价值观分数也仍是前端启发式展示值。
8. **整理输出规则配置**：成员 C 的部分高风险输出规则仍硬编码在 `output_guard.py`，后续可迁移到配置文件统一管理。
9. **补齐提交材料**：项目实训报告、完整测试报告、测试截图、原创性声明和答辩 PPT 尚不在本目录中。

## 十、比赛提交前检查

- 在一台全新电脑上按 README 从零安装并启动成功。
- 无网络或 API 异常时有可演示的降级方案；有网络时能现场调用真实模型。
- 源代码、词库、规则、模型、训练数据、配置、说明文档、测试报告和截图全部放入提交包。
- 使用正式测试集复核拦截率和误判率，报告中的数字与程序现场结果一致。
- 删除个人 API Key、临时日志、缓存和无关文件，不提交四个成员各自的 `.git` 目录。
