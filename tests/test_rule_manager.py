from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from safechat_guard.rule_filter import RuleFilter
from safechat_guard.rule_manager import (
    RuleConflictError,
    RuleImportTooLargeError,
    RuleManager,
    RuleStorageError,
    RuleValidationError,
)


def rule(rule_id: str = "custom-1", **changes):
    value = {
        "id": rule_id,
        "pattern": "蓝色测试短语",
        "pattern_type": "phrase",
        "category": "ad",
        "action": "sanitize",
        "risk_level": "medium",
        "enabled": True,
        "description": "temporary test rule",
    }
    value.update(changes)
    return value


@pytest.fixture
def manager(tmp_path):
    return RuleManager(tmp_path / "data" / "rules" / "user_rules.json")


def test_first_start_creates_versioned_empty_overlay(manager):
    assert manager.metadata()["revision"] == 0
    assert manager.list_rules() == []
    assert manager.storage_path.exists()


@pytest.mark.parametrize("pattern_type", ["keyword", "phrase", "regex"])
def test_add_supported_rule_types(manager, pattern_type):
    pattern = r"蓝色\d{2}" if pattern_type == "regex" else "蓝色标记"
    result = manager.add_rule(rule(pattern_type, pattern_type=pattern_type, pattern=pattern))

    assert result["rule"]["pattern_type"] == pattern_type
    assert result["revision"] == 1


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("pattern", ""),
        ("pattern_type", "glob"),
        ("category", "other"),
        ("action", "pass"),
        ("risk_level", "critical"),
        ("enabled", "true"),
    ],
)
def test_invalid_schema_is_rejected_before_write(manager, field, value):
    before = manager.storage_path.read_bytes()
    with pytest.raises(RuleValidationError):
        manager.add_rule(rule(**{field: value}))
    assert manager.storage_path.read_bytes() == before


def test_unknown_field_and_unsafe_regex_are_rejected(manager):
    with pytest.raises(RuleValidationError, match="unknown field"):
        manager.add_rule({**rule(), "extra": 1})
    with pytest.raises(RuleValidationError, match="nested quantifier"):
        manager.add_rule(rule(pattern_type="regex", pattern=r"(a+)+$"))


def test_duplicate_and_revision_conflict_are_rejected(manager):
    manager.add_rule(rule())
    with pytest.raises(RuleConflictError):
        manager.add_rule(rule())
    with pytest.raises(RuleConflictError, match="revision conflict"):
        manager.add_rule(rule("custom-2"), expected_revision=0)


def test_second_manager_observes_latest_disk_revision(manager):
    second = RuleManager(manager.storage_path)
    manager.add_rule(rule("first"), expected_revision=0)

    with pytest.raises(RuleConflictError, match="revision conflict"):
        second.add_rule(rule("second"), expected_revision=0)
    second.add_rule(rule("second"), expected_revision=1)
    manager.reload()
    assert {item["id"] for item in manager.list_rules()} == {"first", "second"}

def test_update_enable_disable_delete_and_backup(manager):
    created = manager.add_rule(rule())
    disabled = manager.disable_rule("custom-1", expected_revision=created["revision"])
    assert disabled["rule"]["enabled"] is False
    enabled = manager.enable_rule("custom-1", expected_revision=disabled["revision"])
    assert enabled["rule"]["enabled"] is True
    updated = manager.update_rule(
        "custom-1",
        {"description": "updated"},
        expected_revision=enabled["revision"],
    )
    assert updated["rule"]["description"] == "updated"
    deleted = manager.delete_rule("custom-1", expected_revision=updated["revision"])
    assert deleted["revision"] == 5
    assert manager.list_rules() == []
    assert manager.backup_path.exists()


def test_write_failure_preserves_previous_file(manager, monkeypatch):
    manager.add_rule(rule())
    before = manager.storage_path.read_bytes()

    def fail_replace(source, destination):
        raise OSError("simulated")

    monkeypatch.setattr("safechat_guard.rule_manager.os.replace", fail_replace)
    with pytest.raises(RuleStorageError):
        manager.add_rule(rule("custom-2"))
    assert manager.storage_path.read_bytes() == before
    assert [item["id"] for item in manager.list_rules()] == ["custom-1"]


def test_corrupt_reload_preserves_last_valid_memory(manager):
    manager.add_rule(rule())
    manager.storage_path.write_text("{broken", encoding="utf-8")

    with pytest.raises(RuleStorageError):
        manager.reload()
    assert manager.get_rule("custom-1")["pattern"] == "蓝色测试短语"


def test_threaded_adds_do_not_lose_updates(manager):
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda index: manager.add_rule(rule(f"r-{index}")), range(30)))
    assert len(manager.list_rules()) == 30
    assert manager.revision == 30


def test_csv_dry_run_does_not_write(manager):
    content = (
        "id,pattern,pattern_type,category,action,risk_level,enabled,description\n"
        "csv-1,蓝色词,keyword,ad,sanitize,medium,true,imported\n"
    )
    before = manager.storage_path.read_bytes()
    report = manager.import_csv(content, dry_run=True)
    assert report["valid"] == 1 and report["dry_run"] is True
    assert manager.storage_path.read_bytes() == before


def test_json_import_is_atomic_when_any_row_is_invalid(manager):
    content = json.dumps(
        [
            rule("json-1"),
            rule("json-2", pattern_type="regex", pattern="("),
        ],
        ensure_ascii=False,
    )
    before = manager.storage_path.read_bytes()
    with pytest.raises(RuleValidationError) as error:
        manager.import_json(content)
    assert error.value.details["invalid"] == 1
    assert manager.storage_path.read_bytes() == before
    assert manager.list_rules() == []


def test_json_dry_run_and_malformed_json(manager):
    before = manager.storage_path.read_bytes()
    report = manager.import_json(
        json.dumps([rule("dry-json")], ensure_ascii=False), dry_run=True
    )
    assert report["valid"] == 1
    assert manager.storage_path.read_bytes() == before
    with pytest.raises(RuleValidationError, match="malformed"):
        manager.import_json("{broken", dry_run=True)


def test_import_rule_count_limit_is_atomic(manager, monkeypatch):
    monkeypatch.setattr("safechat_guard.rule_manager.MAX_IMPORT_RULES", 1)
    content = json.dumps([rule("one"), rule("two")], ensure_ascii=False)
    before = manager.storage_path.read_bytes()
    with pytest.raises(RuleImportTooLargeError, match="too many"):
        manager.import_json(content)
    assert manager.storage_path.read_bytes() == before


def test_default_storage_path_is_independent_of_current_directory(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    expected = project_root.resolve() / "data" / "rules" / "user_rules.json"
    assert RuleManager.default_path(project_root) == expected


def test_non_string_enum_values_are_validation_errors(manager):
    for field in ("pattern_type", "category", "action", "risk_level"):
        with pytest.raises(RuleValidationError):
            manager.add_rule(rule(**{field: []}))

def test_import_duplicate_and_update_mode(manager):
    manager.add_rule(rule("json-1"))
    duplicate = json.dumps([rule("json-1")], ensure_ascii=False)
    report = manager.import_json(duplicate, dry_run=True)
    assert report["duplicate"] == 1 and report["invalid"] == 1

    updated = rule("json-1", description="replacement")
    result = manager.import_json(
        json.dumps([updated], ensure_ascii=False),
        mode="update",
        expected_revision=1,
    )
    assert result["imported"] == 1
    assert manager.get_rule("json-1")["description"] == "replacement"


def test_import_limits_and_utf8_validation(manager):
    with pytest.raises(RuleImportTooLargeError):
        manager.import_json(b"x" * (1024 * 1024 + 1), dry_run=True)
    with pytest.raises(RuleValidationError, match="UTF-8"):
        manager.import_csv(b"\xff", dry_run=True)


def test_formula_description_is_reported_without_echoing_pattern(manager):
    content = (
        "id,pattern,pattern_type,category,action,risk_level,enabled,description\n"
        "csv-1,秘密模式,keyword,ad,sanitize,medium,true,=CMD()\n"
    )
    report = manager.import_csv(content, dry_run=True)
    assert report["invalid"] == 1
    assert "秘密模式" not in json.dumps(report, ensure_ascii=False)


def test_rule_filter_overlay_reload_lifecycle(manager, tmp_path):
    lexicons = tmp_path / "lexicons"
    lexicons.mkdir()
    regex_path = tmp_path / "regex.json"
    regex_path.write_text("[]", encoding="utf-8")
    filter_ = RuleFilter(str(lexicons), str(regex_path), rule_manager=manager)

    created = manager.add_rule(rule(pattern="蓝色命中"))
    assert filter_.reload_user_rules() is True
    assert filter_.detect("这里有蓝色命中")

    disabled = manager.disable_rule("custom-1", expected_revision=created["revision"])
    assert filter_.reload_if_changed() is True
    assert filter_.detect("这里有蓝色命中") == []

    manager.enable_rule("custom-1", expected_revision=disabled["revision"])
    assert filter_.reload_if_changed() is True
    assert filter_.detect("这里有蓝色命中")

    manager.delete_rule("custom-1", expected_revision=3)
    assert filter_.reload_if_changed() is True
    assert filter_.detect("这里有蓝色命中") == []


def test_failed_filter_reload_keeps_previous_compiled_overlay(manager, tmp_path):
    lexicons = tmp_path / "lexicons"
    lexicons.mkdir()
    regex_path = tmp_path / "regex.json"
    regex_path.write_text("[]", encoding="utf-8")
    manager.add_rule(rule(pattern="保留命中"))
    filter_ = RuleFilter(str(lexicons), str(regex_path), rule_manager=manager)
    manager.storage_path.write_text("{broken", encoding="utf-8")

    assert filter_.reload_if_changed() is False
    assert filter_.reload_error_code == "USER_RULE_RELOAD_FAILED"
    assert filter_.detect("仍应保留命中") != []

def test_candidate_compilation_failure_does_not_write_or_increment_revision(
    manager, tmp_path, monkeypatch
):
    lexicons = tmp_path / "candidate-lexicons"
    lexicons.mkdir()
    regex_path = tmp_path / "candidate-regex.json"
    regex_path.write_text("[]", encoding="utf-8")
    filter_ = RuleFilter(str(lexicons), str(regex_path), rule_manager=manager)
    before = manager.storage_path.read_bytes()

    def reject_candidate(rules, revision):
        raise RuleValidationError("candidate rejected")

    monkeypatch.setattr(filter_, "validate_candidate_rules", reject_candidate)
    with pytest.raises(RuleValidationError, match="candidate rejected"):
        manager.add_rule(rule(action="block"))

    assert manager.storage_path.read_bytes() == before
    assert manager.revision == 0
    assert manager.list_rules() == []
    assert filter_.user_rules_revision == 0
