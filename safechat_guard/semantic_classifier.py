from .models import Detection


class SemanticClassifier:
    """Second-layer semantic detector placeholder.

    The baseline uses simple phrases so the full system can run immediately.
    Replace this class with a Chinese safety classifier or your XLM-R/RoBERTa
    model after the rule-based baseline is stable.
    """

    def detect(self, text: str) -> list[Detection]:
        suspicious_patterns = ["add me", "wechat", "contact me", "guaranteed pass", "agent service"]
        matches = [item for item in suspicious_patterns if item.lower() in text.lower()]
        if not matches:
            return []
        return [
            Detection(
                category="semantic_suspicious",
                level="low",
                score=45,
                reason="semantic layer marked this text as suspicious",
                source="semantic_mock",
                matches=matches,
            )
        ]
