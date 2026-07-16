import pytest

from app import build_detect_payload, parse_json_object, require_text


def test_detect_payload_exposes_stable_contract():
    payload = build_detect_payload("加 V-X 领取优 惠 券，名额有限")

    assert payload["status"] == "success"
    assert {
        "model_loaded",
        "model_error",
        "normalized_text",
        "semantic_scores",
        "detections",
    } <= payload.keys()


@pytest.mark.parametrize("raw", ["null", "[]", '"text"', "1"])
def test_json_body_must_be_an_object(raw):
    with pytest.raises(ValueError, match="must be an object"):
        parse_json_object(raw)


@pytest.mark.parametrize("value", [None, [], {}, 0, "", "   "])
def test_text_fields_reject_empty_or_non_string_values(value):
    with pytest.raises(ValueError, match="non-empty string"):
        require_text({"text": value}, "text")