from frontend.styles import GLOBAL_CSS


def test_design_system_defines_required_semantic_tokens_without_forbidden_effects():
    required_tokens = (
        "--sg-blue:#2563d9",
        "--sg-success:#2f7d5b",
        "--sg-warning:#b7791f",
        "--sg-danger:#b94a55",
        "--sg-purple:#6d5bd0",
        "--sg-line:#d9e2ef",
    )
    assert all(token in GLOBAL_CSS for token in required_tokens)
    lowered = GLOBAL_CSS.lower()
    assert "gradient" not in lowered
    assert "backdrop-filter" not in lowered
    assert "text-shadow" not in lowered


def test_design_system_has_desktop_tablet_and_mobile_layout_contracts():
    assert "max-width:1200px" in GLOBAL_CSS
    assert "@media (max-width:900px)" in GLOBAL_CSS
    assert "@media (max-width:760px)" in GLOBAL_CSS
    assert "@media (max-width:430px)" in GLOBAL_CSS
    assert "min-width:100%" in GLOBAL_CSS


def test_status_badges_have_pass_sanitize_and_block_semantics():
    assert ".sg-badge.pass" in GLOBAL_CSS
    assert ".sg-badge.sanitize" in GLOBAL_CSS
    assert ".sg-badge.block" in GLOBAL_CSS
