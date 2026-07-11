from safechat_guard.pipeline import SafeChatPipeline
from safechat_guard.models import Detection


def test_normal_message_passes():
    pipeline = SafeChatPipeline.from_config("config.yaml")
    result = pipeline.handle_chat("请介绍一下人工智能安全竞赛的基本流程。")

    assert result["allowed"] is True
    assert result["input_filter"]["action"] == "pass"
    assert result["input_filter"]["risk_score"] == 0
    assert result["input_filter"]["normalized_text"]
    assert result["input_filter"]["detections"] == []
    assert {"reply", "input_filter", "output_filter"} <= result.keys()


def test_ad_message_sanitized():
    pipeline = SafeChatPipeline.from_config("config.yaml")
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


def test_phone_regex_records_and_sanitizes_real_match():
    pipeline = SafeChatPipeline.from_config("config.yaml")
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


def test_rule_and_semantic_results_are_both_preserved(monkeypatch):
    pipeline = SafeChatPipeline.from_config("config.yaml")
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

    assert calls == [filtered["normalized_text"]]
    assert {"regex", "semantic_ml"} <= sources


def test_output_filter_runs_rule_and_semantic_layers(monkeypatch):
    pipeline = SafeChatPipeline.from_config("config.yaml")
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


def test_stats_exposes_semantic_classifier_status():
    status = SafeChatPipeline.from_config("config.yaml").stats()[
        "semantic_classifier"
    ]

    assert set(status) == {
        "enabled",
        "loaded",
        "model_path",
        "model_type",
        "classes",
        "error",
    }
    assert status["loaded"] is False
    assert status["error"]
