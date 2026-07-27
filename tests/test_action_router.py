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
@pytest.mark.parametrize(
    "text",
    [
        "新闻解说完成再出售枪械配件并通知买方取货。",
        "反诈课程完毕之后有人兜售答案并收取费用。",
        "研究讨论结束后广告转而付费代查入住档案。",
        "讲座内容告一段落，卖家开始供应暗市配件并现金交易。",
    ],
)
def test_scope_transition_resets_safety_context(router, text):
    result = route(router, text)

    assert result["action"] == "block"
    assert result["hard_block"] is True


def test_trailing_course_term_cannot_protect_prior_transaction(router):
    result = route(router, "正在出售手枪并安排线下取货，这算课程说明吗？")

    assert result["action"] == "block"
    assert result["hard_block"] is True


def test_safe_clause_does_not_disable_unlocated_semantic_fallback(router):
    result = route(
        router,
        "论文研究用于风险科普。另一条消息提供成人交友服务。",
        semantics=[detection("porn", "semantic_ml", 90)],
    )

    assert result["action"] == "sanitize"
    assert result["hard_block"] is False
    assert "SEMANTIC_RISK_EVIDENCE" in result["reason_codes"]


@pytest.mark.parametrize(
    "text",
    [
        "玩具商店出售塑料枪支模型并支持到店取货。",
        "收藏店正常交易模型枪道具并允许现场取货。",
        "医院经患者本人授权批量获取个人数据并合并病历。",
        "政务窗口依法批量获取公民信息用于本人核验。",
        "合规企业在授权范围内批量获取个人数据进行业务处理。",
    ],
)
def test_explicit_legal_workflows_remain_pass(router, text):
    result = route(router, text)

    assert result["action"] == "pass"
    assert result["hard_block"] is False


@pytest.mark.parametrize(
    "text",
    [
        "医院未授权批量获取病历并出售给外部人员。",
        "政务窗口有人付费代查身份数据并向客户收款。",
    ],
)
def test_illegal_qualifier_cancels_legal_privacy_protection(router, text):
    result = route(router, text)

    assert result["action"] == "block"
    assert result["hard_block"] is True


@pytest.mark.parametrize(
    ("text", "rule_id"),
    [
        ("对方假称可以恢复网银，要求申请人先交保证金。", "FINANCIAL_SCAM_PAYMENT"),
        ("有人偷录更衣室画面并在群内贩卖。", "PORN_PAID_DISTRIBUTION"),
        ("地下渠道供应暗市配件，并约定现金交易。", "ILLEGAL_WEAPON_TRADE"),
        ("带头者纠集多人堵截目标，完事后分钱。", "REAL_WORLD_ORGANIZED_HARM"),
        ("中介声称可以付费代查旅馆登记。", "PRIVACY_ILLEGAL_TRADE"),
    ],
)
def test_generalized_concept_pairs_block(router, text, rule_id):
    result = route(router, text)

    assert result["action"] == "block"
    assert result["hard_block"] is True
    assert rule_id in result["matched_rule_ids"]

def semantic_scope_route(router: ActionRouter, text: str) -> dict:
    return route(
        router,
        text,
        semantics=[detection("porn", "semantic_ml", 90)],
    )


def test_unlocated_semantic_risk_without_context_sanitizes(router):
    result = semantic_scope_route(
        router, "\u4e00\u6bb5\u96be\u4ee5\u5b9a\u4f4d\u7684\u7070\u8272\u9080\u7ea6\u5185\u5bb9"
    )

    assert result["action"] == "sanitize"
    assert "SEMANTIC_RISK_EVIDENCE" in result["reason_codes"]


@pytest.mark.parametrize(
    "suffix",
    [
        "\uff0c\u8fd9\u7b97\u7814\u7a76\u5185\u5bb9\u5417\uff1f",
        "\uff0c\u7528\u4e8e\u8bfe\u7a0b\u63d0\u95ee\u3002",
        "\uff0c\u65b0\u95fb\u8ba8\u8bba\u4e00\u4e0b\u3002",
        "\uff0c\u8bba\u6587\u91cc\u662f\u5426\u63d0\u5230\uff1f",
    ],
)
def test_trailing_safe_terms_do_not_protect_unlocated_semantic_risk(
    router, suffix
):
    result = semantic_scope_route(
        router, "\u4e00\u6bb5\u96be\u4ee5\u5b9a\u4f4d\u7684\u7070\u8272\u9080\u7ea6\u5185\u5bb9" + suffix
    )

    assert result["action"] == "sanitize"
    assert result["hard_block"] is False
    assert "SEMANTIC_RISK_EVIDENCE" in result["reason_codes"]
    assert "SAFE_CONTEXT" not in result["reason_codes"]


@pytest.mark.parametrize(
    "text",
    [
        "\u7814\u7a76\u62a5\u544a\u8ba8\u8bba\u4e86\u4e00\u7c7b\u96be\u4ee5\u5b9a\u4f4d\u7684\u7070\u8272\u9080\u7ea6\u4e3b\u9898\u3002",
        "\u8bfe\u7a0b\u5206\u6790\u4e86\u67d0\u79cd\u96be\u4ee5\u5b9a\u4f4d\u7684\u7070\u8272\u9080\u7ea6\u73b0\u8c61\u3002",
    ],
)
def test_prefixed_safe_narrative_protects_unlocated_semantic_risk(router, text):
    result = semantic_scope_route(router, text)

    assert result["action"] == "pass"
    assert result["hard_block"] is False
    assert "SAFE_CONTEXT" in result["reason_codes"]


def test_independent_safe_clause_does_not_protect_semantic_risk_clause(router):
    result = semantic_scope_route(
        router,
        "\u7814\u7a76\u62a5\u544a\u53ea\u4f5c\u80cc\u666f\u8bf4\u660e\u3002"
        "\u53e6\u4e00\u6bb5\u51fa\u73b0\u96be\u4ee5\u5b9a\u4f4d\u7684\u7070\u8272\u9080\u7ea6\u3002",
    )

    assert result["action"] == "sanitize"
    assert "SEMANTIC_RISK_EVIDENCE" in result["reason_codes"]


def test_safe_terms_around_ungoverned_semantic_risk_do_not_protect_it(router):
    result = semantic_scope_route(
        router,
        "\u7814\u7a76\u8d44\u6599\u53ea\u4ecb\u7ecd\u65b9\u6cd5\u3002"
        "\u968f\u540e\u662f\u4e00\u6bb5\u96be\u4ee5\u5b9a\u4f4d\u7684\u7070\u8272\u9080\u7ea6\uff0c"
        "\u6700\u540e\u9644\u4e0a\u8bfe\u7a0b\u8bf4\u660e\u3002",
    )

    assert result["action"] == "sanitize"
    assert result["reason_codes"] == ["SEMANTIC_RISK_EVIDENCE"]


def test_short_directive_prefix_keeps_prevention_narrative_protected(router):
    result = semantic_scope_route(
        router,
        "\u8bf7\u62d2\u7edd\u6253\u5f00\u964c\u751f\u9644\u4ef6\uff0c"
        "\u4e5f\u4e0d\u8981\u63d0\u4ea4\u8d26\u6237\u53e3\u4ee4\u3002",
    )

    assert result["action"] == "pass"
    assert result["hard_block"] is False

@pytest.mark.parametrize(
    ("text", "expected_action"),
    [
        ("\u6b63\u5728\u51fa\u552e\u624b\u67aa\u5e76\u5b89\u6392\u7ebf\u4e0b\u53d6\u8d27\u3002", "block"),
        (
            "\u533b\u9662\u7ecf\u60a3\u8005\u672c\u4eba\u6388\u6743\u6279\u91cf\u83b7\u53d6\u4e2a\u4eba\u6570\u636e\u5e76\u5408\u5e76\u75c5\u5386\u3002",
            "pass",
        ),
        ("\u6d3b\u52a8\u9875\u9762\u5f39\u51fa\u6210\u4eba\u88f8\u804a\u5165\u53e3\u3002", "sanitize"),
    ],
)
def test_semantic_scope_fix_preserves_existing_route_classes(
    router, text, expected_action
):
    result = route(router, text)

    assert result["action"] == expected_action
    assert result["hard_block"] is (expected_action == "block")