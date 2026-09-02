from __future__ import annotations

import json
import os
from copy import deepcopy
from typing import Any

from .rule_manager import (
    RuleManagerError,
    RuleNotFoundError,
    apply_rule_transaction,
)


class RuleWritesDisabledError(PermissionError):
    """Raised when a policy mutation is attempted in read-only mode."""


class RuleManagementService:
    """Product service over the existing RuleManager and RuleFilter."""

    def __init__(self, pipeline: Any, *, writes_enabled: bool | None = None) -> None:
        self.pipeline = pipeline
        self.manager = pipeline.rule_manager
        self.rule_filter = pipeline.rule_filter
        self.writes_enabled = (
            os.getenv("SAFECHAT_ENABLE_RULE_WRITES", "false").strip().lower()
            == "true"
            if writes_enabled is None
            else bool(writes_enabled)
        )

    def catalog(
        self,
        *,
        query: str = "",
        category: str | None = None,
        pattern_type: str | None = None,
        enabled: bool | None = None,
    ) -> dict[str, Any]:
        rules = self._all_rules()
        needle = query.strip().casefold()
        if needle:
            rules = [
                rule for rule in rules
                if needle in rule["id"].casefold()
                or needle in rule["description"].casefold()
                or needle in rule["pattern"].casefold()
            ]
        if category:
            rules = [rule for rule in rules if rule["category"] == category]
        if pattern_type:
            rules = [rule for rule in rules if rule["pattern_type"] == pattern_type]
        if enabled is not None:
            rules = [rule for rule in rules if rule["enabled"] is enabled]
        return {
            "rules": rules,
            "writes_enabled": self.writes_enabled,
            **self.manager.metadata(),
        }

    def get_rule(self, rule_id: str) -> dict[str, Any]:
        for rule in self._all_rules():
            if rule["id"] == rule_id:
                return rule
        raise RuleNotFoundError("rule does not exist")

    def validate_candidate(self, rule: dict[str, Any]) -> dict[str, Any]:
        payload = json.dumps([rule], ensure_ascii=False)
        report = self.manager.validate_import(payload, format="json", mode="create")
        if report["invalid"]:
            return {key: value for key, value in report.items() if key != "_rules"}
        self.rule_filter.validate_candidate_rules(
            report["_rules"], self.manager.revision + 1
        )
        return {
            **{key: value for key, value in report.items() if key != "_rules"},
            "candidate": deepcopy(report["_rules"][0]),
        }

    def test_rule(self, rule_id: str, text: str) -> dict[str, Any]:
        rule = self.get_rule(rule_id)
        normalized = self.pipeline.normalizer.normalize_views(text)
        result = self.rule_filter.test_candidate_rule(
            {**rule, "enabled": True}, normalized.adversarial_text or normalized.normalized_text
        )
        return {
            **result,
            "normalized_text": normalized.normalized_text,
            "normalization_changed": normalized.normalized_text != text,
        }

    def versions(self) -> list[dict[str, Any]]:
        current = self.manager.snapshot_state()
        versions = [self._version_metadata(current, "current")]
        backup = self.manager.backup_snapshot()
        if backup is not None:
            versions.append(self._version_metadata(backup, "backup"))
        return versions

    def diff(self) -> dict[str, Any]:
        current = self.manager.snapshot_state()
        backup = self.manager.backup_snapshot()
        if backup is None:
            return {"available": False, "added": [], "removed": [], "changed": []}
        current_rules = {rule["id"]: rule for rule in current["rules"]}
        backup_rules = {rule["id"]: rule for rule in backup["rules"]}
        common = sorted(current_rules.keys() & backup_rules.keys())
        return {
            "available": True,
            "from_revision": backup["revision"],
            "to_revision": current["revision"],
            "added": sorted(current_rules.keys() - backup_rules.keys()),
            "removed": sorted(backup_rules.keys() - current_rules.keys()),
            "changed": [
                {
                    "id": rule_id,
                    "fields": sorted(
                        key for key in current_rules[rule_id]
                        if current_rules[rule_id].get(key)
                        != backup_rules[rule_id].get(key)
                    ),
                }
                for rule_id in common
                if current_rules[rule_id] != backup_rules[rule_id]
            ],
        }

    def publish_candidate(
        self, rule: dict[str, Any], *, expected_revision: int
    ) -> dict[str, Any]:
        self._require_writes()
        validation = self.validate_candidate(rule)
        if validation["invalid"]:
            raise RuleManagerError("candidate validation failed", details=validation)
        return apply_rule_transaction(
            self.manager,
            self.rule_filter,
            lambda: self.manager.add_rule(
                rule, expected_revision=expected_revision
            ),
        )

    def set_enabled(
        self, rule_id: str, enabled: bool, *, expected_revision: int
    ) -> dict[str, Any]:
        self._require_writes()
        operation = self.manager.enable_rule if enabled else self.manager.disable_rule
        return apply_rule_transaction(
            self.manager,
            self.rule_filter,
            lambda: operation(rule_id, expected_revision=expected_revision),
        )

    def rollback(self, *, expected_revision: int) -> dict[str, Any]:
        self._require_writes()
        return apply_rule_transaction(
            self.manager,
            self.rule_filter,
            lambda: self.manager.rollback_to_backup(
                expected_revision=expected_revision
            ),
        )

    def _require_writes(self) -> None:
        if not self.writes_enabled:
            raise RuleWritesDisabledError(
                "rule writes are disabled; set SAFECHAT_ENABLE_RULE_WRITES=true"
            )

    def _all_rules(self) -> list[dict[str, Any]]:
        builtins: list[dict[str, Any]] = []
        for category, words in sorted(self.rule_filter.words.items()):
            for index, word in enumerate(words):
                builtins.append({
                    "id": f"builtin:keyword:{category}:{index}",
                    "pattern": word, "pattern_type": "keyword",
                    "category": category,
                    "action": "block" if category in {"porn", "violence"} else "sanitize",
                    "risk_level": "high" if category in {"porn", "violence"} else "medium",
                    "enabled": True, "description": "内置关键词规则",
                    "source": "builtin", "read_only": True,
                })
        for index, rule in enumerate(self.rule_filter.regex_rules):
            builtins.append({
                "id": f"builtin:regex:{index}",
                "pattern": str(rule.get("pattern", "")), "pattern_type": "regex",
                "category": str(rule.get("category", "sensitive")),
                "action": "block" if int(rule.get("score", 60)) >= 80 else "sanitize",
                "risk_level": str(rule.get("level", "medium")),
                "enabled": True,
                "description": str(rule.get("reason", "内置正则规则")),
                "source": "builtin", "read_only": True,
            })
        users = [
            {**rule, "read_only": False}
            for rule in self.manager.list_rules()
        ]
        return [*builtins, *users]

    @staticmethod
    def _version_metadata(state: dict[str, Any], kind: str) -> dict[str, Any]:
        return {
            "kind": kind, "revision": state["revision"],
            "content_sha256": state["content_sha256"],
            "rule_count": len(state["rules"]),
        }
