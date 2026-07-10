from safechat_guard.semantic_classifier import SemanticClassifier


class FakeSemanticModel:
    classes_ = ("normal", "ad")

    def predict_proba(self, texts):
        assert texts
        return [[0.1, 0.9]]


def test_rule_classifier_works_without_optional_model():
    classifier = SemanticClassifier(model_path=None)

    detections = classifier.detect("请加微信领取资料")

    assert detections
    assert detections[0].category == "ad"
    assert detections[0].source == "semantic_rule"


def test_optional_model_adds_detection_for_unmatched_text():
    classifier = SemanticClassifier(model_path=None)
    classifier.model = FakeSemanticModel()

    detections = classifier.detect("这是一条需要模型判断的文本")

    assert len(detections) == 1
    assert detections[0].category == "ad"
    assert detections[0].source == "semantic_ml"
