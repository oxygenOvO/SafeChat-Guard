from __future__ import annotations

import json
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def production_config_without_model(tmp_path: Path) -> Path:
    """Copy the production configs into an isolated root without model artifacts."""
    config = json.loads((PROJECT_ROOT / "config.yaml").read_text(encoding="utf-8"))
    config["logging"]["path"] = str(tmp_path / "events.jsonl")

    semantic_source = PROJECT_ROOT / config["semantic"]["config_path"]
    semantic_target = tmp_path / config["semantic"]["config_path"]
    semantic_target.parent.mkdir(parents=True, exist_ok=True)
    semantic_target.write_bytes(semantic_source.read_bytes())

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return config_path
