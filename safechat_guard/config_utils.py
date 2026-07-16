DEFAULT_SEMANTIC_THRESHOLDS = {
    "ad": 0.65,
    "porn": 0.55,
    "violence": 0.55,
    "sensitive": 0.65,
}


def load_semantic_thresholds(config: dict | None) -> dict[str, float]:
    config = config or {}
    raw = config.get("semantic_thresholds", {})
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ValueError("semantic_thresholds must be an object")

    thresholds = dict(DEFAULT_SEMANTIC_THRESHOLDS)
    for category, value in raw.items():
        if category not in DEFAULT_SEMANTIC_THRESHOLDS:
            raise ValueError(f"unsupported semantic threshold category: {category}")
        try:
            threshold = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"semantic threshold for {category} must be numeric") from exc
        if not 0 <= threshold <= 1:
            raise ValueError(f"semantic threshold for {category} must be between 0 and 1")
        thresholds[category] = threshold
    return thresholds
