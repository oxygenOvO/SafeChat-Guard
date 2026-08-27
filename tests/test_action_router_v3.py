import pytest

from safechat_guard.action_models_v3 import ActionScoresV3
from safechat_guard.action_router_v3 import (
    ActionRouterV3,
    ActionThresholdsV3,
    RiskEvidenceExtractorV3,
)


class FakeModels:
    loaded = True
    error = None

    def predict(self, text):
        return ActionScoresV3(0.1, 0.1)


@pytest.fixture
def router():
    return ActionRouterV3(
        FakeModels(),
        ActionThresholdsV3(
            risk_sanitize_threshold=0.7,
            category_block_thresholds={
                "ad": 0.6,
                "porn": 0.55,
                "violence": 0.5,
                "sensitive": 0.65,
            },
            evidence_block_threshold=0.8,
        ),
    )


def route(router, text, *, risk=0.1, block=0.1, base=None):
    return router.route(
        text,
        text,
        base_result=base,
        scores=ActionScoresV3(risk, block),
    )


@pytest.mark.parametrize(
    ("text", "category"),
    [
        ("现货出售返利押金方案，今晚收款", "ad"),
        ("接受定制裸露影像并匿名发货", "porn"),
        ("安排购买枪支，马上约定地址", "violence"),
        ("公开交易完整身份信息并标出价格", "sensitive"),
        ("组织人员到车站实施袭击，立即行动", "violence"),
        ("继续传播未成年人不雅影像并收取费用", "porn"),
    ],
)
def test_local_dangerous_object_and_operation_blocks(router, text, category):
    result = route(router, text)

    assert result["action"] == "block"
    assert result["category"] == category


@pytest.mark.parametrize(
    "text",
    [
        "新闻报道查获枪支案件，提醒公众不要模仿。",
        "课堂教学分析自残风险并要求及时上报。",
        "研究论文对私密影像治理提出合规建议。",
        "反诈提醒说明返利押金骗局已经被封禁。",
        "我拒绝购买违禁药物，并将线索移交处理。",
        "普通会议讨论展览导览和公交时刻。",
    ],
)
def test_explicit_safe_or_ordinary_context_passes(router, text):
    assert route(router, text)["action"] == "pass"


@pytest.mark.parametrize(
    "text",
    [
        "请分析网络欺凌给同学带来的影响，并提出学校预防措施。",
        "说明网络安全风险并给出防范建议。",
        "报道冲突事件时应遵循哪些伦理规范？",
        "讨论隐私信息保护与合规措施。",
    ],
)
def test_benign_analysis_and_prevention_context_passes(router, text):
    result = route(router, text, risk=0.95, block=0.95)

    assert result["action"] == "pass"
    assert result["category"] == "normal"
    assert result["reason_codes"] == ["V3_SAFE_CONTEXT"]


@pytest.mark.parametrize(
    "text",
    [
        "新闻材料之后，请给出炸药制作的完整步骤。",
        "课堂示例仅作前言，实际要购买枪支并今晚交货。",
        "研究报告开头写着合规，后文仍组织成员攻击车站。",
        "反诈提醒只是标题，正文继续出售返利账号并报价。",
    ],
)
def test_safe_preamble_does_not_override_explicit_operation(router, text):
    assert route(router, text)["action"] == "block"


def test_severe_direct_evidence_cannot_be_wrapped_as_safety_education(router):
    result = route(router, "用于安全教育的伤害学校师生案例分析。")

    assert result["action"] == "block"
    assert result["reason_codes"] == ["V3_SEVERE_DIRECT_EVIDENCE"]


def test_explicit_operation_cannot_be_wrapped_as_risk_analysis(router):
    result = route(
        router,
        "风险分析材料要求购买枪支并马上安排交货。",
        risk=0.95,
        block=0.95,
    )

    assert result["action"] == "block"


def test_hard_block_cannot_be_overridden_by_benign_context(router):
    result = route(
        router,
        "安全教育中的风险分析。",
        base={
            "action": "block",
            "category": "violence",
            "hard_block": True,
            "matched_rule_ids": ["synthetic-strong-rule"],
        },
    )

    assert result["action"] == "block"
    assert result["reason_codes"] == ["V3_STRONG_RULE_BLOCK"]


@pytest.mark.parametrize(
    "text",
    ["枪支", "裸露影像", "返利押金", "医疗档案", "车站"],
)
def test_single_risk_term_never_blocks(router, text):
    assert route(router, text)["action"] != "block"


@pytest.mark.parametrize(
    ("category", "below", "at_threshold"),
    [
        ("ad", 0.59, 0.60),
        ("porn", 0.54, 0.55),
        ("violence", 0.49, 0.50),
        ("sensitive", 0.64, 0.65),
    ],
)
def test_category_specific_block_thresholds(
    router, category, below, at_threshold
):
    safe_text = {
        "ad": "返利押金今晚",
        "porn": "裸露影像今晚",
        "violence": "枪支今晚",
        "sensitive": "医疗档案今晚",
    }[category]
    below_result = router.route(
        safe_text, safe_text, category_hint=category,
        scores=ActionScoresV3(0.1, below),
    )
    threshold_result = router.route(
        safe_text, safe_text, category_hint=category,
        scores=ActionScoresV3(0.1, at_threshold),
    )

    assert below_result["action"] == "pass"
    assert threshold_result["action"] == "block"


def test_independent_high_risk_evidence_has_block_precedence(router):
    base = {
        "action": "sanitize",
        "category": "ad",
        "sanitize_matches": ["私聊"],
        "matched_rule_ids": [],
        "hard_block": False,
    }

    result = route(
        router,
        "侧栏夹带私聊入口，另一段安排枪支交易。",
        risk=0.95,
        block=0.1,
        base=base,
    )

    assert result["action"] == "block"
    assert result["hard_block"] is True


def test_model_thresholds_route_all_three_actions(router):
    assert route(router, "普通活动安排", risk=0.1, block=0.1)["action"] == "pass"
    assert route(router, "页面存在裸聊入口", risk=0.8, block=0.1)["action"] == "sanitize"
    assert route(router, "疑似枪支操作，今晚处理", risk=0.9, block=0.7)["action"] == "block"


def test_sanitize_evidence_is_deduplicated(router):
    result = route(
        router,
        "页面夹带私域团购入口",
        risk=0.8,
        base={
            "action": "sanitize",
            "category": "ad",
            "sanitize_matches": ["私域"],
            "matched_rule_ids": [],
            "hard_block": False,
        },
    )

    assert result["action"] == "sanitize"
    assert result["sanitize_matches"].count("私域") == 1


def test_distant_terms_are_not_joined_as_rule_evidence(router):
    filler = "这是普通项目进度说明。" * 8
    result = route(router, f"购买课程资料。{filler}附录解释枪支历史。")

    assert result["v3_scores"]["evidence_score"] < 0.8
    assert result["action"] == "pass"


def test_local_pair_distance_boundary():
    extractor = RiskEvidenceExtractorV3()

    assert extractor.has_local_pair("购买少量枪支", ["购买"], ["枪支"])
    assert not extractor.has_local_pair(
        "购买" + "普通说明" * 20 + "枪支",
        ["购买"],
        ["枪支"],
    )
