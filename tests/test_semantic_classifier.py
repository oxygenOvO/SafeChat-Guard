import pytest

from safechat_guard.semantic_classifier import (
    DEFAULT_CATEGORY_THRESHOLDS,
    DEFAULT_MIN_MARGIN,
    SemanticClassifier,
)


class FakeSemanticModel:
    def __init__(self, classes, probabilities):
        self.classes_ = tuple(classes)
        self.probabilities = list(probabilities)

    def predict_proba(self, texts):
        assert texts
        return [self.probabilities]


def _classifier(tmp_path, classes, probabilities, **kwargs):
    classifier = SemanticClassifier(
        model_path=str(tmp_path / "missing-for-test.joblib"),
        **kwargs,
    )
    classifier.model = FakeSemanticModel(classes, probabilities)
    classifier._error = None
    return classifier


def test_missing_model_has_explicit_status(tmp_path):
    classifier = SemanticClassifier(model_path=str(tmp_path / "missing.pkl"))

    assert classifier.status()["loaded"] is False
    assert classifier.status()["error"] == "model file not found"
    assert classifier.detect("测试文本") == []

    distribution = classifier.predict_distribution("测试文本")
    assert distribution["available"] is False
    assert distribution["error"] == "model file not found"


def test_loaded_model_status_lists_classes_and_threshold_configuration(tmp_path):
    classifier = _classifier(tmp_path, ("normal", "ad"), (0.1, 0.9))

    status = classifier.status()

    assert status["enabled"] is True
    assert status["loaded"] is True
    assert status["model_type"] == "sklearn_pipeline"
    assert status["classes"] == ["normal", "ad"]
    assert status["category_thresholds"] == DEFAULT_CATEGORY_THRESHOLDS
    assert status["min_margin"] == DEFAULT_MIN_MARGIN
    assert classifier.detect("需要模型判断的文本")[0].source == "semantic_ml"


def test_predict_distribution_matches_raw_predict_proba(tmp_path):
    classes = ("ad", "normal", "porn", "sensitive", "violence")
    probabilities = (0.07, 0.46, 0.04, 0.12, 0.31)
    classifier = _classifier(tmp_path, classes, probabilities)

    distribution = classifier.predict_distribution("安全测试文本")
    raw = classifier.model.predict_proba(["安全测试文本"])[0]

    assert distribution == {
        "available": True,
        "top_category": "normal",
        "top_probability": 0.46,
        "probabilities": {
            "normal": 0.46,
            "ad": 0.07,
            "porn": 0.04,
            "sensitive": 0.12,
            "violence": 0.31,
        },
        "risk_detection_emitted": False,
    }
    assert distribution["probabilities"] == dict(zip(classes, raw, strict=True))


def test_distribution_reports_detection_gate_without_changing_detect(tmp_path):
    classifier = _classifier(
        tmp_path,
        ("normal", "violence"),
        (0.20, 0.80),
    )

    before = classifier.detect("合成风险文本")
    distribution = classifier.predict_distribution("合成风险文本")
    after = classifier.detect("合成风险文本")

    assert distribution["top_category"] == "violence"
    assert distribution["top_probability"] == 0.80
    assert distribution["risk_detection_emitted"] is True
    assert [item.__dict__ for item in before] == [item.__dict__ for item in after]


def test_normal_top_label_never_falls_back_to_second_risk_class(tmp_path):
    classifier = _classifier(
        tmp_path,
        ("normal", "ad", "porn"),
        (0.40, 0.35, 0.25),
        category_thresholds={"ad": 0.20, "porn": 0.20},
        min_margin=0.0,
    )

    assert classifier.detect("normal最高但风险类别接近") == []


def test_risk_probability_below_category_threshold_returns_no_detection(tmp_path):
    classifier = _classifier(
        tmp_path,
        ("normal", "ad"),
        (0.40, 0.60),
        min_margin=0.0,
    )

    assert classifier.detect("低置信度广告") == []


def test_risk_probability_above_threshold_returns_detection(tmp_path):
    classifier = _classifier(
        tmp_path,
        ("normal", "ad"),
        (0.20, 0.80),
    )

    detections = classifier.detect("高置信度广告")

    assert len(detections) == 1
    assert detections[0].category == "ad"
    assert detections[0].source == "semantic_ml"


def test_risk_margin_below_configured_minimum_returns_no_detection(tmp_path):
    classifier = _classifier(
        tmp_path,
        ("normal", "porn"),
        (0.46, 0.54),
        category_thresholds={"porn": 0.50},
        min_margin=0.10,
    )

    assert classifier.detect("类别接近normal") == []


@pytest.mark.parametrize(
    ("category_thresholds", "min_margin"),
    [
        ({"ad": -0.01}, 0.10),
        ({"ad": 1.01}, 0.10),
        (None, -0.01),
        (None, 1.01),
    ],
)
def test_invalid_threshold_configuration_is_rejected(
    tmp_path,
    category_thresholds,
    min_margin,
):
    with pytest.raises(ValueError):
        SemanticClassifier(
            model_path=str(tmp_path / "missing.joblib"),
            category_thresholds=category_thresholds,
            min_margin=min_margin,
        )
