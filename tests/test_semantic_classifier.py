from safechat_guard.semantic_classifier import SemanticClassifier


class FakeSemanticModel:
    classes_ = ("normal", "ad")

    def predict_proba(self, texts):
        assert texts
        return [[0.1, 0.9]]


def test_missing_model_has_explicit_status(tmp_path):
    classifier = SemanticClassifier(model_path=str(tmp_path / "missing.pkl"))

    assert classifier.status()["loaded"] is False
    assert classifier.status()["error"] == "model file not found"
    assert classifier.detect("测试文本") == []


def test_loaded_model_status_lists_classes():
    classifier = SemanticClassifier()
    classifier.model = FakeSemanticModel()
    classifier._error = None

    status = classifier.status()

    assert status["enabled"] is True
    assert status["loaded"] is True
    assert status["model_type"] == "sklearn_pipeline"
    assert status["classes"] == ["normal", "ad"]
    assert classifier.detect("需要模型判断的文本")[0].source == "semantic_ml"
