from safechat_guard.pipeline import SafeChatPipeline
from safechat_guard.models import Detection


def test_normal_message_passes(production_config_without_model):
    pipeline = SafeChatPipeline.from_config(str(production_config_without_model))
    result = pipeline.handle_chat("请介绍一下人工智能安全竞赛的基本流程。")

    assert result["allowed"] is True
    assert result["input_filter"]["action"] == "pass"
    assert result["input_filter"]["risk_score"] == 0
    assert result["input_filter"]["normalized_text"]
    assert result["input_filter"]["detections"] == []
    assert {"reply", "input_filter", "output_filter"} <= result.keys()


def test_ad_message_sanitized(production_config_without_model):
    pipeline = SafeChatPipeline.from_config(str(production_config_without_model))
    result = pipeline.handle_chat("加vx领取内部资料。")
    filtered = result["input_filter"]

    assert "微信" in filtered["normalized_text"]
    assert "vx" not in filtered["normalized_text"]
    assert filtered["action"] in {"sanitize", "block"}
    assert filtered["risk_score"] >= 40
    assert filtered["detections"]
    assert "ad" in {item["category"] for item in filtered["detections"]}
    if filtered["action"] == "sanitize":
        assert filtered["sanitized_text"]


def test_phone_regex_records_and_sanitizes_real_match(production_config_without_model):
    pipeline = SafeChatPipeline.from_config(str(production_config_without_model))
    filtered = pipeline.handle_chat(
        "请联系我 13812345678 获取资料。"
    )["input_filter"]
    regex_detections = [
        item for item in filtered["detections"] if item["source"] == "regex"
    ]

    assert regex_detections
    assert any("13812345678" in item["matches"] for item in regex_detections)
    assert filtered["action"] == "sanitize"
    assert "13812345678" not in filtered["sanitized_text"]


def test_rule_and_semantic_results_are_both_preserved(
    monkeypatch, production_config_without_model
):
    pipeline = SafeChatPipeline.from_config(str(production_config_without_model))
    calls = []

    def fake_detect(text):
        calls.append(text)
        return [
            Detection(
                category="ad",
                level="medium",
                score=70,
                reason="fake semantic result",
                source="semantic_ml",
                matches=["semantic evidence"],
            )
        ]

    monkeypatch.setattr(pipeline.semantic_classifier, "detect", fake_detect)
    filtered = pipeline._filter_text(
        "请联系我 13812345678 获取资料。",
        stage="input",
    )
    sources = {item["source"] for item in filtered["detections"]}

    assert calls[0] == filtered["normalized_text"]
    assert len(calls) == 2
    assert filtered["action"] == "sanitize"
    assert {"regex", "semantic_ml"} <= sources
    assert filtered["rewrite_recheck"]["detections"]
    assert {
        detection["source"]
        for detection in filtered["rewrite_recheck"]["detections"]
    } == {"semantic_ml"}


def test_output_filter_runs_rule_and_semantic_layers(
    monkeypatch, production_config_without_model
):
    pipeline = SafeChatPipeline.from_config(str(production_config_without_model))
    monkeypatch.setattr(
        pipeline.semantic_classifier,
        "detect",
        lambda text: [
            Detection("ad", "medium", 70, "fake", "semantic_ml", ["evidence"])
        ],
    )

    result = pipeline._filter_output("请联系我 13812345678 获取资料。")

    assert {"regex", "semantic_ml"} <= {
        item["source"] for item in result["detections"]
    }


def test_stats_exposes_semantic_classifier_status(production_config_without_model):
    status = SafeChatPipeline.from_config(str(production_config_without_model)).stats()[
        "semantic_classifier"
    ]

    assert {
        "enabled",
        "loaded",
        "model_path",
        "model_type",
        "classes",
        "error",
        "category_thresholds",
        "min_margin",
        "model_sha256_expected",
        "model_sha256_actual",
        "model_sha256_verified",
        "required",
        "config_path",
    } <= set(status)
    assert status["model_path"].endswith("semantic_model_v2.joblib")
    assert status["required"] is False
    assert status["loaded"] is False
    assert status["enabled"] is False
    assert status["error"] == "model file not found"
    assert status["model_sha256_verified"] is False
    assert set(status["category_thresholds"]) == {
        "ad",
        "porn",
        "violence",
        "sensitive",
    }


def _semantic_detection(category="ad"):
    return Detection(
        category=category,
        level="medium",
        score=60,
        reason=f"semantic {category} result",
        source="semantic_ml",
        matches=[f"{category}: 29.78%"],
    )


def test_coupon_phrase_alone_has_no_rule_ad_detection(
    production_config_without_model,
):
    pipeline = SafeChatPipeline.from_config(str(production_config_without_model))
    normalized = pipeline.normalizer.normalize("领取优惠券，名额有限")

    rule_detections = pipeline.rule_filter.detect(normalized)
    rule_ad_detections = [
        detection
        for detection in rule_detections
        if detection.category == "ad" and detection.source in {"keyword", "regex"}
    ]

    assert rule_ad_detections == []
    assert pipeline.sanitizer.sanitize(normalized, []) == normalized


def test_contact_ad_variants_keep_only_semantic_ad_after_rewrite(
    monkeypatch, production_config_without_model
):
    pipeline = SafeChatPipeline.from_config(str(production_config_without_model))
    monkeypatch.setattr(
        pipeline.semantic_classifier,
        "detect",
        lambda _text: [_semantic_detection("ad")],
    )
    cases = [
        (
            "加 V-X 领取优 惠 券，名额有限",
            "[联系方式已隐藏]领取优惠券，名额有限",
            "领取优惠券",
            "名额有限",
        ),
        (
            "加 V-X 领取优惠券，数量有限",
            "[联系方式已隐藏]领取优惠券，数量有限",
            "领取优惠券",
            "数量有限",
        ),
        (
            "联系微信领取优惠券，今日截止",
            "[联系方式已隐藏]领取优惠券，今日截止",
            "领取优惠券",
            "今日截止",
        ),
    ]

    for text, expected, retained_phrase, retained_tail in cases:
        filtered = pipeline.detect_text(text)
        initial_rule_ad = [
            detection
            for detection in filtered["detections"]
            if detection["category"] == "ad"
            and detection["source"] in {"keyword", "regex"}
        ]

        assert initial_rule_ad
        assert filtered["action"] == "sanitize"
        assert filtered["sanitized_text"] == expected
        assert "[联系方式已隐藏]" in filtered["sanitized_text"]
        assert retained_phrase in filtered["sanitized_text"]
        assert retained_tail in filtered["sanitized_text"]
        assert filtered["rewrite_recheck"] is not None
        assert filtered["rewrite_recheck"]["detections"]
        assert all(
            detection["source"] == "semantic_ml"
            and detection["category"] == "ad"
            for detection in filtered["rewrite_recheck"]["detections"]
        )


def test_contact_wechat_is_minimally_sanitized(production_config_without_model):
    pipeline = SafeChatPipeline.from_config(str(production_config_without_model))

    filtered = pipeline.detect_text("联系微信了解详情")

    assert filtered["action"] == "sanitize"
    assert filtered["sanitized_text"] == "[联系方式已隐藏]了解详情"
    assert filtered["rewrite_recheck"] is not None
    assert filtered["rewrite_recheck"]["detections"] == []


def test_residual_rule_detection_still_blocks(
    monkeypatch, production_config_without_model
):
    pipeline = SafeChatPipeline.from_config(str(production_config_without_model))
    real_rule_detect = pipeline.rule_filter.detect

    def detect_with_residual_rule(text):
        detections = real_rule_detect(text)
        if "[联系方式已隐藏]" in text:
            detections.append(
                Detection(
                    category="ad",
                    level="medium",
                    score=55,
                    reason="residual rule evidence",
                    source="regex",
                    matches=["联系方式"],
                )
            )
        return detections

    monkeypatch.setattr(pipeline.rule_filter, "detect", detect_with_residual_rule)
    monkeypatch.setattr(
        pipeline.semantic_classifier,
        "detect",
        lambda _text: [_semantic_detection("ad")],
    )

    filtered = pipeline.detect_text("加 V-X 领取优惠券，数量有限")

    assert filtered["action"] == "block"
    assert filtered["sanitized_text"] is None
    assert any(
        detection["source"] == "regex"
        for detection in filtered["rewrite_recheck"]["detections"]
    )


def test_residual_non_ad_semantic_risk_still_blocks(
    monkeypatch, production_config_without_model
):
    for category in ("porn", "violence", "sensitive"):
        pipeline = SafeChatPipeline.from_config(str(production_config_without_model))

        def fake_semantic_detect(text, residual_category=category):
            if "加微信" in text:
                return []
            return [_semantic_detection(residual_category)]

        monkeypatch.setattr(
            pipeline.semantic_classifier,
            "detect",
            fake_semantic_detect,
        )

        filtered = pipeline.detect_text("加 V-X 领取优惠券，数量有限")

        assert filtered["action"] == "block"
        assert filtered["sanitized_text"] is None
        assert {
            detection["category"]
            for detection in filtered["rewrite_recheck"]["detections"]
        } == {category}
