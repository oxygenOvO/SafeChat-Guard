import pytest

from safechat_guard.config_utils import (
    DEFAULT_SEMANTIC_THRESHOLDS,
    load_semantic_thresholds,
)
from safechat_guard.semantic_classifier import SemanticClassifier


class FakeSemanticModel:
    classes_ = ("normal", "ad")

    def __init__(self, ad_probability: float):
        self.ad_probability = ad_probability

    def predict_proba(self, texts):
        assert texts
        return [[1.0 - self.ad_probability, self.ad_probability]]


def test_missing_threshold_config_uses_defaults():
    assert load_semantic_thresholds({}) == DEFAULT_SEMANTIC_THRESHOLDS


def test_threshold_config_overrides_single_category():
    thresholds = load_semantic_thresholds({"semantic_thresholds": {"ad": 0.7}})

    assert thresholds["ad"] == 0.7
    assert thresholds["porn"] == DEFAULT_SEMANTIC_THRESHOLDS["porn"]


def test_invalid_threshold_category_has_clear_error():
    with pytest.raises(ValueError, match="unsupported semantic threshold category"):
        load_semantic_thresholds({"semantic_thresholds": {"unknown": 0.5}})


def test_invalid_threshold_value_has_clear_error():
    with pytest.raises(ValueError, match="between 0 and 1"):
        load_semantic_thresholds({"semantic_thresholds": {"ad": 1.5}})


def test_semantic_detection_respects_configured_threshold():
    classifier = SemanticClassifier(thresholds=load_semantic_thresholds({"semantic_thresholds": {"ad": 0.7}}))
    classifier.model = FakeSemanticModel(ad_probability=0.6)
    classifier._error = None

    assert classifier.detect("sample text") == []

    classifier.thresholds["ad"] = 0.55
    assert classifier.detect("sample text")[0].category == "ad"
