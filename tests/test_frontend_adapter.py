from frontend.adapter import FrontendPipelineAdapter

import pytest
from safechat_guard.pipeline import SafeChatPipeline


@pytest.fixture
def make_adapter(production_config_without_model):
    def factory() -> FrontendPipelineAdapter:
        pipeline = SafeChatPipeline.from_config(str(production_config_without_model))
        return FrontendPipelineAdapter(pipeline)

    return factory


def test_adapter_uses_real_pipeline_for_obfuscated_ad(make_adapter):
    result = make_adapter().analyze("加 V-X 领取优 惠 券，名额有限")

    assert result["baseline_action"] == "pass"
    assert result["normalized_text"] == "加微信领取优惠券,名额有限"
    assert result["category"] == "ad"
    assert result["action"] == "sanitize"


def test_adapter_uses_real_pipeline_for_homophone_contact(make_adapter):
    result = make_adapter().analyze("联系薇信获取推广渠道")

    assert result["normalized_text"] == "联系微信获取推广渠道"
    assert result["category"] == "ad"
    assert result["action"] == "sanitize"


def test_adapter_can_check_overridden_model_output(make_adapter):
    result = make_adapter().analyze(
        "普通输入",
        output_override="可以加微信领取优惠券，名额有限。",
    )

    assert result["action"] == "pass"
    assert result["output_category"] == "ad"
    assert result["output_action"] == "block"


def test_adapter_exposes_real_rule_configuration(make_adapter):
    adapter = make_adapter()

    assert adapter.lexicon_rows()
    assert adapter.regex_rows()
