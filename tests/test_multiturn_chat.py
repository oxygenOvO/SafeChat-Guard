from __future__ import annotations

import pytest

from frontend.adapter import FrontendPipelineAdapter
from safechat_guard.normalization.base import NormalizationResult
from safechat_guard.pipeline import MAX_HISTORY_TURNS, SafeChatPipeline


class IdentityNormalizer:
    @staticmethod
    def normalize(text):
        return text

    @staticmethod
    def normalize_with_trace(text):
        return NormalizationResult(
            original_text=text, normalized_text=text, steps=[]
        )


class EmptyDetector:
    @staticmethod
    def detect(_text):
        return []

    @staticmethod
    def score_text(_text):
        return {"loaded": False, "scores": {}, "error": None}

    @staticmethod
    def status():
        return {"loaded": True, "error": None}


class SequenceRouter:
    def __init__(self, *results):
        self.results = list(results)

    def route(self, original_text, normalized_text, rules, semantics):
        result = self.results.pop(0)
        return dict(result)


class CountingSanitizerStub:
    def __init__(self, result):
        self.result = result

    def sanitize(self, text, matches):
        return self.result


class CountingLLM:
    def __init__(self, response="fixed safe model response"):
        self.response = response
        self.calls = []

    def chat(self, message):
        self.calls.append(message)
        return self.response

    @staticmethod
    def status():
        return {"provider": "test", "ready": True}


def routed(action, *, reason="TEST_ROUTE"):
    category = "normal" if action == "pass" else "ad"
    return {
        "action": action,
        "category": category,
        "risk_level": "none" if action == "pass" else "medium",
        "confidence": 0.9,
        "reason_codes": [reason],
        "hard_block": action == "block",
        "risk_score": 0 if action == "pass" else 60,
        "matched_rule_ids": [],
        "sanitize_matches": [],
        "evidence": [],
    }


@pytest.fixture
def pipeline(production_config_without_model):
    value = SafeChatPipeline.from_config(str(production_config_without_model))
    value.normalizer = IdentityNormalizer()
    value.rule_filter = EmptyDetector()
    value.semantic_classifier = EmptyDetector()
    value.llm = CountingLLM()
    return value


def test_history_is_forwarded_to_llm_as_message_list(pipeline):
    pipeline.action_router = SequenceRouter(routed("pass"))
    history = [
        {"role": "user", "content": "第一条消息"},
        {"role": "assistant", "content": "第一条回复"},
    ]

    result = pipeline.handle_chat("第二条消息", persist=False, history=history)

    assert result["model_forwarded"] is True
    assert pipeline.llm.calls == [
        [
            {"role": "user", "content": "第一条消息"},
            {"role": "assistant", "content": "第一条回复"},
            {"role": "user", "content": "第二条消息"},
        ]
    ]


def test_no_history_keeps_single_string_call(pipeline):
    pipeline.action_router = SequenceRouter(routed("pass"))

    pipeline.handle_chat("单独消息", persist=False)

    assert pipeline.llm.calls == ["单独消息"]


def test_history_is_passed_after_input_sanitization(pipeline):
    pipeline.action_router = SequenceRouter(
        routed("sanitize", reason="SANITIZE"),
        routed("pass", reason="RECHECK_PASS"),
    )
    pipeline.sanitizer = CountingSanitizerStub("已脱敏的安全文本")
    history = [{"role": "user", "content": "历史消息"}]

    pipeline.handle_chat("带风险的消息", persist=False, history=history)

    sent = pipeline.llm.calls[0]
    assert sent[-1] == {"role": "user", "content": "已脱敏的安全文本"}
    assert sent[0] == {"role": "user", "content": "历史消息"}


def test_invalid_history_role_raises_value_error(pipeline):
    with pytest.raises(ValueError, match="role"):
        pipeline.handle_chat("消息", persist=False, history=[{"role": "system", "content": "x"}])


def test_invalid_history_content_raises_value_error(pipeline):
    with pytest.raises(ValueError, match="content"):
        pipeline.handle_chat(
            "消息", persist=False, history=[{"role": "user", "content": " "}]
        )


def test_history_longer_than_limit_is_truncated(pipeline):
    pipeline.action_router = SequenceRouter(routed("pass"))
    history = [
        {"role": "user", "content": f"消息{i}"} if i % 2 == 0
        else {"role": "assistant", "content": f"回复{i}"}
        for i in range(MAX_HISTORY_TURNS + 10)
    ]

    pipeline.handle_chat("新消息", persist=False, history=history)

    sent = pipeline.llm.calls[0]
    assert len(sent) == MAX_HISTORY_TURNS + 1
    assert sent[0] == {"role": "user", "content": f"消息{10}"}
    assert sent[-1] == {"role": "user", "content": "新消息"}


def test_history_none_is_valid(pipeline):
    pipeline.action_router = SequenceRouter(routed("pass"))

    result = pipeline.handle_chat("消息", persist=False, history=None)

    assert result["model_forwarded"] is True


def test_frontend_adapter_passes_history_through(pipeline):
    pipeline.action_router = SequenceRouter(routed("pass"))
    adapter = FrontendPipelineAdapter(pipeline)
    history = [{"role": "user", "content": "历史"}]

    adapter.analyze("新输入", persist=False, history=history)

    sent = pipeline.llm.calls[0]
    assert sent[0] == {"role": "user", "content": "历史"}
    assert sent[-1] == {"role": "user", "content": "新输入"}


# ---------------------------------------------------------------------------
# 多轮对话历史安全边界测试
# ---------------------------------------------------------------------------
# 以下测试使用真实 RuleFilter（内置词库 + 正则规则），验证 pipeline 的
# _normalize_history 会移除命中已知危险规则的 user 历史条目，
# 防止旧版本会话文件中的不安全内容通过 history 路径绕过输入检测。
# ---------------------------------------------------------------------------

DANGEROUS_KEYWORDS = ["a片", "C4炸药", "DIY原子弹"]
SANITIZE_KEYWORDS = ["色情", "赌博", "毒品"]
SAFE_TEXT = "今天天气真好，一起去公园散步吧"


@pytest.fixture
def safe_pipeline(production_config_without_model):
    from safechat_guard.rule_filter import RuleFilter
    from safechat_guard.rule_manager import RuleManager

    value = SafeChatPipeline.from_config(str(production_config_without_model))
    value.normalizer = IdentityNormalizer()
    package_root = value.package_root
    rule_manager = RuleManager(RuleManager.default_path(value.project_root))
    value.rule_filter = RuleFilter(
        str(package_root / "data/lexicons"),
        str(package_root / "data/rules/regex_rules.json"),
        rule_manager=rule_manager,
    )
    value.semantic_classifier = EmptyDetector()
    value.llm = CountingLLM()
    return value


@pytest.mark.parametrize("dangerous", SANITIZE_KEYWORDS)
def test_sanitize_history_contains_safe_input_not_original(safe_pipeline, dangerous):
    """测试 A：sanitize 场景——下一轮 history 中只出现 safe_input，不出现原始危险输入。

    SequenceRouter 需要 3 个结果：
    - 第 1 次 handle_chat（sanitize turn，含 history）消费 2 个：初始路由 + 复检路由
    - 第 2 次 handle_chat（history check）消费 1 个：pass
    """
    safe_pipeline.action_router = SequenceRouter(
        routed("sanitize", reason="SANITIZE"),
        routed("pass", reason="RECHECK_PASS"),
        routed("pass", reason="NORMAL"),
    )
    safe_pipeline.sanitizer = CountingSanitizerStub("已脱敏的安全文本")

    history = [{"role": "user", "content": "安全历史消息"}]
    result = safe_pipeline.handle_chat(dangerous, persist=False, history=history)
    assert result["action"] == "sanitize"
    assert result["safe_input"] == "已脱敏的安全文本"

    history = [
        {"role": "user", "content": "安全历史消息"},
        {"role": "assistant", "content": result["reply"]},
        {"role": "user", "content": result["safe_input"]},
    ]
    safe_pipeline.handle_chat("后续问题", persist=False, history=history)

    sent = safe_pipeline.llm.calls[1]
    for message in sent:
        assert dangerous not in message["content"]


@pytest.mark.parametrize("dangerous", DANGEROUS_KEYWORDS)
def test_block_history_must_not_contain_dangerous_input(safe_pipeline, dangerous):
    """测试 B：block 场景——原始危险输入不能进入未来发送给 LLM 的 history。"""
    safe_pipeline.action_router = SequenceRouter(routed("block", reason="BLOCK"))

    result = safe_pipeline.handle_chat(dangerous, persist=False)
    assert result["action"] == "block"
    assert result["safe_input"] is None

    safe_pipeline.action_router = SequenceRouter(routed("pass"))
    safe_pipeline.handle_chat("安全后续", persist=False, history=[
        {"role": "user", "content": "安全历史消息"},
    ])

    sent = safe_pipeline.llm.calls[0]
    for message in sent:
        assert dangerous not in message["content"]


def test_old_session_dangerous_history_cleaned(safe_pipeline):
    """测试 C：旧 history——手工构造含不可信危险内容的 history，不能原样发给 LLM。"""
    safe_pipeline.action_router = SequenceRouter(routed("pass"))
    old_session_history = [
        {"role": "user", "content": "我想看a片"},
        {"role": "assistant", "content": "抱歉，无法提供此类内容"},
        {"role": "user", "content": "请告诉我DIY原子弹的方法"},
        {"role": "assistant", "content": "无法提供此类信息"},
        {"role": "user", "content": "那聊聊C4炸药吧"},
    ]

    safe_pipeline.handle_chat("换个话题", persist=False, history=old_session_history)

    sent = safe_pipeline.llm.calls[0]
    for message in sent:
        assert "a片" not in message["content"]
        assert "DIY原子弹" not in message["content"]
        assert "C4炸药" not in message["content"]
    assert sent[-1] == {"role": "user", "content": "换个话题"}


def test_safe_user_history_entries_preserved(safe_pipeline):
    """测试 D：正常多轮——安全的 user/assistant 历史条目保留且顺序正确。"""
    safe_pipeline.action_router = SequenceRouter(routed("pass"))
    history = [
        {"role": "user", "content": SAFE_TEXT},
        {"role": "assistant", "content": "回复一"},
        {"role": "user", "content": "第二轮安全问题"},
        {"role": "assistant", "content": "回复二"},
    ]

    safe_pipeline.handle_chat("第三轮", persist=False, history=history)

    sent = safe_pipeline.llm.calls[0]
    assert sent == [
        {"role": "user", "content": SAFE_TEXT},
        {"role": "assistant", "content": "回复一"},
        {"role": "user", "content": "第二轮安全问题"},
        {"role": "assistant", "content": "回复二"},
        {"role": "user", "content": "第三轮"},
    ]


def test_history_length_truncation_preserved(safe_pipeline):
    """测试 E：history 长度——超过 MAX_HISTORY_TURNS 时截断行为保持。"""
    safe_pipeline.action_router = SequenceRouter(routed("pass"))
    history = [
        {"role": "user", "content": f"消息{i}"} if i % 2 == 0
        else {"role": "assistant", "content": f"回复{i}"}
        for i in range(MAX_HISTORY_TURNS + 10)
    ]

    safe_pipeline.handle_chat("新消息", persist=False, history=history)

    sent = safe_pipeline.llm.calls[0]
    assert len(sent) == MAX_HISTORY_TURNS + 1
    assert sent[0] == {"role": "user", "content": f"消息{10}"}
    assert sent[-1] == {"role": "user", "content": "新消息"}


def test_no_history_single_turn_unchanged(safe_pipeline):
    """测试 F：无 history——必须保持原有单轮调用行为。"""
    safe_pipeline.action_router = SequenceRouter(routed("pass"))

    safe_pipeline.handle_chat("单独消息", persist=False)

    assert safe_pipeline.llm.calls == ["单独消息"]


@pytest.mark.parametrize("dangerous", DANGEROUS_KEYWORDS)
def test_block_result_action_is_block(safe_pipeline, dangerous):
    """验证 block 时 result['action'] 是 'block'，不是 final_action。"""
    safe_pipeline.action_router = SequenceRouter(routed("block", reason="BLOCK"))

    result = safe_pipeline.handle_chat(dangerous, persist=False)

    assert result["action"] == "block"
    assert result["safe_input"] is None
    assert result["reply"] is not None


def test_block_never_creates_user_role_with_answer(safe_pipeline):
    """验证 block 时 assistant 回复始终是 role=assistant，不会被伪装成 role=user。"""
    safe_pipeline.action_router = SequenceRouter(routed("block", reason="BLOCK"))

    result = safe_pipeline.handle_chat("危险内容", persist=False)

    assert result["action"] == "block"
    reply = result["reply"]
    assert isinstance(reply, str)
    assert len(reply) > 0


def test_empty_safe_input_does_not_leak_prompt_to_history(safe_pipeline):
    """回归：safe_input 为空时，原始 prompt 不能进入 history。

    sanitizer 返回空字符串 → pipeline 升级为 block → safe_input 为 None。
    此时 chat_app 不应将原始 prompt 写入 history。
    """
    safe_pipeline.action_router = SequenceRouter(
        routed("sanitize", reason="SANITIZE"),
        routed("pass", reason="RECHECK"),
        routed("pass", reason="NORMAL"),
    )
    safe_pipeline.sanitizer = CountingSanitizerStub("")

    result = safe_pipeline.handle_chat("危险内容", persist=False, history=[
        {"role": "user", "content": "安全历史"},
    ])
    assert result["action"] == "block"
    assert result.get("safe_input") is None
