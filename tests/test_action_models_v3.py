from pathlib import Path

import pytest

from safechat_guard.action_models_v3 import ActionModelBundleV3
from safechat_guard.action_router_v3 import ActionThresholdsV3


ROOT = Path(__file__).resolve().parents[1]


def test_frozen_action_models_load_with_verified_hashes():
    _, payload = ActionThresholdsV3.load(
        ROOT / "config/action_thresholds_v3.json"
    )
    models = ActionModelBundleV3(
        ROOT / payload["risk_model_path"],
        ROOT / payload["block_model_path"],
        expected_risk_sha256=payload["risk_model_sha256"],
        expected_block_sha256=payload["block_model_sha256"],
    )

    assert models.loaded
    assert models.status()["hashes_verified"] is True


def test_action_model_hash_mismatch_fails_closed():
    _, payload = ActionThresholdsV3.load(
        ROOT / "config/action_thresholds_v3.json"
    )
    models = ActionModelBundleV3(
        ROOT / payload["risk_model_path"],
        ROOT / payload["block_model_path"],
        expected_risk_sha256="0" * 64,
        expected_block_sha256=payload["block_model_sha256"],
    )

    assert not models.loaded
    assert models.error == "risk model sha256 mismatch"


@pytest.mark.parametrize("value", ["", "g" * 64, "1" * 63, "1" * 65])
def test_action_model_rejects_invalid_expected_hash(value):
    with pytest.raises(ValueError, match="sha256"):
        ActionModelBundleV3(
            ROOT / "models/risk_model_v3.joblib",
            ROOT / "models/block_model_v3.joblib",
            expected_risk_sha256=value,
        )
