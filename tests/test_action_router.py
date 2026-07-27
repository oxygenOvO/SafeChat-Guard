from __future__ import annotations

import json
from pathlib import Path

import pytest

from safechat_guard.action_router import ActionRouter
from safechat_guard.models import Detection


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RULES_PATH = PROJECT_ROOT / "config/action_rules_v1.json"
REQUIRED_FIELDS = {
    "action",
    "category",
    "risk_level",
    "confidence",
    "reason_codes",
    "hard_block",
    "risk_score",
    "matched_rule_ids",
    "sanitize_matches",
    "evidence",
}


@pytest.fixture
def router() -> ActionRouter:
    return ActionRouter(RULES_PATH)


def detection(category: str, source: str, score: int = 80) -> Detection:
    return Detection(
        category=category,
        level="high" if score >= 80 else "medium",
        score=score,
        reason="synthetic unit-test evidence",
        source=source,
        matches=[f"{category}-evidence"],
    )


def route(
    router: ActionRouter,
    text: str,
    rules: list[Detection] | None = None,
    semantics: list[Detection] | None = None,
) -> dict:
    return router.route(text, text, rules or [], semantics or [])


def test_configuration_loads_and_return_fields_are_bounded(router):
    result = route(router, "今天的会议安排在下午三点。")

    assert set(result) == REQUIRED_FIELDS
    assert result["action"] == "pass"
    assert result["category"] == "normal"
    assert 0.0 <= result["confidence"] <= 1.0
    assert 0 <= result["risk_score"] <= 100
    assert result["reason_codes"] == ["NO_RISK_EVIDENCE"]


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda value: value.update(schema_version=3), "schema_version"),
        (lambda value: value["rule_families"][0].update(category="normal"), "risk category"),
        (lambda value: value["rule_families"][0].update(confidence=1.5), "confidence"),
        (
            lambda value: value["rule_families"][1].update(
                id=value["rule_families"][0]["id"]
            ),
            "duplicate rule id",
        ),
    ],
)
def test_invalid_configuration_is_rejected(tmp_path, mutate, message):
    payload = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    mutate(payload)
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        ActionRouter(path)


@pytest.mark.parametrize(
    ("text", "rule_id", "category"),
    [
        (
            "所谓免审贷款要求申请人先转账保证金，到账后才办理。",
            "FINANCIAL_SCAM_PAYMENT",
            "ad",
        ),
        (
            "有人打包出售露骨私密照，并按下载次数收费。",
            "PORN_PAID_DISTRIBUTION",
            "porn",
        ),
        (
            "卖家发布违禁武器报价，并约买方在线下交货。",
            "ILLEGAL_WEAPON_TRADE",
            "violence",
        ),
        (
            "群主号召成员携带棍棒围堵当事人，统一动手。",
            "REAL_WORLD_ORGANIZED_HARM",
            "violence",
        ),
        (
            "中介宣称可以非法查询出行轨迹并出售给客户。",
            "PRIVACY_ILLEGAL_TRADE",
            "sensitive",
        ),
        (
            "该极端组织要求新人宣誓效忠，并继续招募成员。",
            "EXTREMIST_RECRUITMENT",
            "sensitive",
        ),
        (
            "对方用暗号招揽买家，声称可提供违禁品试用装。",
            "CONTRABAND_TRADE",
            "sensitive",
        ),
    ],
)
def test_seven_compound_rule_families_hard_block(
    router,
    text,
    rule_id,
    category,
):
    result = route(router, text)

    assert result["action"] == "block"
    assert result["risk_level"] == "high"
    assert result["hard_block"] is True
    assert result["category"] == category
    assert rule_id in result["matched_rule_ids"]
    assert result["reason_codes"][0] == "COMPOUND_RULE_MATCH"


@pytest.mark.parametrize(
    "text",
    [
        "报告中只出现了枪支这个风险对象。",
        "讨论材料提到身份证信息。",
        "词汇表收录了成人视频一词。",
    ],
)
def test_single_risk_object_never_hard_blocks(router, text):
    result = route(router, text)

    assert result["hard_block"] is False
    assert result["action"] in {"pass", "sanitize"}


@pytest.mark.parametrize("text", ["今天完成付款。", "文件稍后上传。", "现场可以集结。"])
def test_single_implementation_term_never_hard_blocks(router, text):
    result = route(router, text)

    assert result["hard_block"] is False
    assert result["action"] == "pass"


def test_semantic_only_fixed_high_score_is_not_a_hard_block(router):
    result = route(
        router,
        "一段没有实施细节的模糊文本。",
        semantics=[detection("violence", "semantic_ml", 95)],
    )

    assert result["action"] == "sanitize"
    assert result["hard_block"] is False
    assert result["risk_score"] < 90
    assert result["reason_codes"] == ["SEMANTIC_RISK_EVIDENCE"]


@pytest.mark.parametrize(
    "text",
    [
        "新闻报道回顾了已经制止的非法武器购买案件。",
        "教材说明炸药属于危险品并介绍运输标识。",
        "课程示例要求学生识别刷单骗局。",
        "论文研究讨论偷拍视频传播的治理方法。",
        "反诈提醒：不要为所谓内幕信息付款。",
        "市民举报有人兜售个人数据，平台已处置。",
        "请拒绝购买来路不明的违禁品。",
        "警方通报称相关极端组织招募活动已被制止。",
    ],
)
def test_safety_contexts_protect_non_operational_mentions(router, text):
    result = route(
        router,
        text,
        semantics=[detection("sensitive", "semantic_ml", 80)],
    )

    assert result["action"] == "pass"
    assert result["hard_block"] is False
    assert result["category"] == "normal"
    assert "SAFE_CONTEXT" in result["reason_codes"]


def test_safety_context_does_not_cover_continued_real_transaction(router):
    text = "前半段是反诈提醒，但仍在出售考试答案，并要求立即付款。"

    result = route(router, text)

    assert result["action"] == "block"
    assert result["hard_block"] is True
    assert result["matched_rule_ids"] == ["FINANCIAL_SCAM_PAYMENT"]


def test_negated_implementation_does_not_form_hard_block(router):
    result = route(router, "校园讲座提醒大家不要公开身份证和住址。")

    assert result["action"] == "pass"
    assert result["hard_block"] is False


def test_rule_and_semantic_agreement_strengthens_evidence(router):
    rule_only = route(
        router,
        "出现了一段模糊的私密照描述。",
        rules=[detection("porn", "keyword", 55)],
    )
    agreement = route(
        router,
        "出现了一段模糊的私密照描述。",
        rules=[detection("porn", "keyword", 55)],
        semantics=[detection("porn", "semantic_ml", 60)],
    )

    assert agreement["action"] == "sanitize"
    assert agreement["confidence"] > rule_only["confidence"]
    assert "RULE_SEMANTIC_AGREEMENT" in agreement["reason_codes"]


def test_rule_semantic_conflict_has_deterministic_rule_priority(router):
    result = route(
        router,
        "一段被检测器判断不一致的模糊文本。",
        rules=[detection("violence", "keyword", 55)],
        semantics=[detection("porn", "semantic_ml", 95)],
    )

    assert result["action"] == "sanitize"
    assert result["category"] == "violence"
    assert "RULE_SEMANTIC_CONFLICT" in result["reason_codes"]


def test_reason_codes_do_not_contain_complete_input(router):
    text = "某个很长的自造测试输入只包含模糊风险描述而没有现实实施。"
    result = route(
        router,
        text,
        semantics=[detection("ad", "semantic_ml", 60)],
    )

    assert all(text not in code for code in result["reason_codes"])
    assert all(text not in rule_id for rule_id in result["matched_rule_ids"])


@pytest.mark.parametrize(
    "text",
    [
        "反诈提醒到此结束。有人提供试题答案并要求普通付款。",
        "新闻报道已经结束；卖家随后出售改装武器并安排交易。",
        "课程介绍在前。页面下方有人为极端团体招人并号召线下集结。",
        "请注意保护隐私！另一段广告称可未授权查询实时定位并收费提供。",
    ],
)
def test_safe_clause_cannot_cover_later_real_world_action(router, text):
    result = route(router, text)

    assert result["action"] == "block"
    assert result["hard_block"] is True


@pytest.mark.parametrize(
    "text",
    [
        "聊天记录只写了改装武器。",
        "便签上只有上门报复四个字。",
        "标题内容是清除名单。",
        "页面只显示成人视频。",
        "表格字段名为实时定位。",
    ],
)
def test_single_compound_risk_phrase_never_hard_blocks(router, text):
    result = route(router, text)

    assert result["action"] in {"pass", "sanitize"}
    assert result["hard_block"] is False


def test_object_and_implementation_spans_are_independent(router):
    result = route(router, "卖家兜售手枪零件并约买方当面取货。")

    assert result["action"] == "block"
    assert len(result["evidence"]) >= 2
    objects = [item for item in result["evidence"] if item["evidence_type"] == "risk_object"]
    implementations = [item for item in result["evidence"] if item["evidence_type"] == "implementation"]
    assert objects and implementations
    assert objects[0]["clause_index"] == implementations[0]["clause_index"]
    assert objects[0]["end"] <= implementations[0]["start"] or implementations[0]["end"] <= objects[0]["start"]
    distance = max(
        implementations[0]["start"] - objects[0]["end"],
        objects[0]["start"] - implementations[0]["end"],
        0,
    )
    assert distance <= 24


def test_unrelated_clauses_do_not_form_hard_block(router):
    result = route(router, "说明材料提到武器；另一家商店出售普通文具。")

    assert result["action"] == "sanitize"
    assert result["hard_block"] is False


@pytest.mark.parametrize(
    "text",
    [
        "网店出售儿童玩具武器模型，支持正常退货。",
        "足球教练组织前锋加强边路攻击训练。",
        "医院挂号系统查询个人数据仅用于本人核验。",
        "证券课程讲解内幕交易为何违法并提醒投资者远离。",
    ],
)
def test_legal_domain_contexts_pass(router, text):
    result = route(router, text)

    assert result["action"] == "pass"
    assert result["hard_block"] is False


@pytest.mark.parametrize(
    ("text", "rule_id"),
    [
        ("以冻结账户为由催促受害人先汇款，之后承诺放贷。", "FINANCIAL_SCAM_PAYMENT"),
        ("有人兜售针孔拍摄内容，并收费提供私密影像下载。", "PORN_PAID_DISTRIBUTION"),
        ("地下卖家供应手枪零件，并安排双方当面取货。", "ILLEGAL_WEAPON_TRADE"),
        ("群主召集多人去教训目标，事成后按轻重给钱。", "REAL_WORLD_ORGANIZED_HARM"),
        ("中介调取酒店入住档案和移动路线，再有偿提供给客户。", "PRIVACY_ILLEGAL_TRADE"),
        ("激进暴力团伙要求新人表忠心，并拉人加入。", "EXTREMIST_RECRUITMENT"),
        ("卖家用代称兜售违禁药剂，先给试样再收钱。", "CONTRABAND_TRADE"),
    ],
)
def test_common_synonym_compounds_block(router, text, rule_id):
    result = route(router, text)

    assert result["action"] == "block"
    assert result["hard_block"] is True
    assert rule_id in result["matched_rule_ids"]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("confidence", "0.9", "FINANCIAL_SCAM_PAYMENT.confidence"),
        ("risk_score", True, "FINANCIAL_SCAM_PAYMENT.risk_score"),
        ("risk_score", 96.5, "FINANCIAL_SCAM_PAYMENT.risk_score"),
    ],
)
def test_rule_numeric_types_are_strict(tmp_path, field, value, message):
    payload = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    payload["rule_families"][0][field] = value
    path = tmp_path / "invalid-numeric.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        ActionRouter(path)


def test_object_implementation_containment_is_rejected(tmp_path):
    payload = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    family = payload["rule_families"][0]
    family["object_terms"].append("自造重叠词")
    family["implementation_terms"].append("重叠")
    path = tmp_path / "invalid-overlap.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(
        ValueError,
        match="FINANCIAL_SCAM_PAYMENT.object_terms conflicts.*implementation_terms",
    ):
        ActionRouter(path)


@pytest.mark.parametrize(
    ("text", "category"),
    [
        ("停车位留言：再占我的位置就揍你。", "violence"),
        ("口头威胁说再占车位就踢你。", "violence"),
        ("课程页脚写着私下转账可提前解锁资料。", "ad"),
        ("公开备注误写了测试成员正在接受心理治疗。", "sensitive"),
        ("活动页面弹出成人裸聊入口。", "porn"),
    ],
)
def test_independent_medium_risk_rules_sanitize(router, text, category):
    result = route(router, text)

    assert result["action"] == "sanitize"
    assert result["category"] == category
    assert result["hard_block"] is False