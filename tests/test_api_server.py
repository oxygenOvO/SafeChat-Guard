from api_server import build_detect_payload


def test_detect_payload_has_frontend_contract_fields():
    payload = build_detect_payload("加 V-X 领取优 惠 券，名额有限")

    assert payload["status"] == "success"
    assert "model_loaded" in payload
    assert "detections" in payload
    assert "model_error" in payload
    assert "normalized_text" in payload
    assert "semantic_scores" in payload
