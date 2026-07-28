import json
import re
import threading
from pathlib import Path
from typing import Any

from .models import Detection
from .rule_manager import RuleManager, RuleManagerError, RuleValidationError


class _UserOverlayDetection(Detection):
    __slots__ = (
        "_owner_token",
        "_rule_id",
        "_configured_action",
        "_rule_revision",
    )

    def __init__(
        self,
        *,
        owner_token: object,
        rule_id: str,
        configured_action: str,
        rule_revision: int,
        category: str,
        level: str,
        score: int,
        matches: list[str],
    ) -> None:
        super().__init__(
            category=category,
            level=level,
            score=score,
            reason="matched user overlay rule",
            source="rule:user_overlay",
            matches=matches,
        )
        self._owner_token = owner_token
        self._rule_id = rule_id
        self._configured_action = configured_action
        self._rule_revision = rule_revision

class RuleFilter:
    def __init__(
        self,
        lexicon_dir: str,
        regex_path: str,
        *,
        rule_manager: RuleManager | None = None,
    ):
        self.lexicon_dir = Path(lexicon_dir)
        self.regex_path = Path(regex_path)
        self.rule_manager = rule_manager
        self._lock = threading.RLock()
        self._overlay_token = object()
        self.words = self._load_words()
        self.regex_rules = self._load_regex_rules()
        self._compiled_builtin_regex = tuple(
            (rule, re.compile(rule["pattern"], re.IGNORECASE))
            for rule in self.regex_rules
        )
        self._user_matchers: tuple[dict[str, Any], ...] = ()
        self._user_file_signature: tuple[int, int] | None = None
        self.user_rules_revision = 0
        self.reload_error_code: str | None = None
        self._reload_blocked = False
        if self.rule_manager is not None:
            self.reload_user_rules()
            self.rule_manager.set_candidate_validator(
                lambda rules, revision: self.validate_candidate_rules(rules, revision)
            )

    def _load_words(self) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        if not self.lexicon_dir.exists():
            return result
        for path in self.lexicon_dir.glob("*.txt"):
            category = path.stem
            words = []
            for line in path.read_text(encoding="utf-8").splitlines():
                word = line.strip()
                if word and not word.startswith("#"):
                    words.append(word)
            result[category] = words
        return result

    def _load_regex_rules(self) -> list[dict]:
        if not self.regex_path.exists():
            return []
        rules = json.loads(self.regex_path.read_text(encoding="utf-8"))
        valid_rules = []
        for rule in rules:
            pattern = rule.get("pattern", "")
            if not pattern:
                continue
            try:
                re.compile(pattern, re.IGNORECASE)
            except re.error:
                continue
            valid_rules.append(rule)
        return valid_rules

    def reload_if_changed(self) -> bool:
        if self.rule_manager is None or self._reload_blocked:
            return False
        try:
            stat = self.rule_manager.storage_path.stat()
            signature = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            self.reload_error_code = "USER_RULE_STORAGE_UNAVAILABLE"
            return False
        if signature == self._user_file_signature:
            return False
        return self.reload_user_rules()

    def reload_user_rules(self, *, force: bool = False) -> bool:
        """Swap in a validated overlay, retaining the last good copy on error."""
        if self.rule_manager is None or (self._reload_blocked and not force):
            return False
        try:
            metadata = self.rule_manager.reload()
            matchers = self._build_user_matchers(
                self.rule_manager.list_rules(enabled_only=True)
            )
            stat = self.rule_manager.storage_path.stat()
            signature = (stat.st_mtime_ns, stat.st_size)
        except (RuleManagerError, OSError, re.error):
            self.reload_error_code = "USER_RULE_RELOAD_FAILED"
            return False
        with self._lock:
            self._user_matchers = tuple(matchers)
            self.user_rules_revision = int(metadata["revision"])
            self._user_file_signature = signature
            self.reload_error_code = None
            self._reload_blocked = False
        return True

    def validate_candidate_rules(
        self, rules: list[dict[str, Any]], revision: int
    ) -> None:
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
            raise RuleValidationError("candidate revision must be a non-negative integer")
        enabled = [rule for rule in rules if rule.get("enabled") is True]
        try:
            self._build_user_matchers(enabled)
        except (KeyError, TypeError, re.error) as exc:
            raise RuleValidationError("candidate user rules failed compilation") from exc

    @staticmethod
    def _build_user_matchers(
        rules: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        matchers: list[dict[str, Any]] = []
        for rule in rules:
            matcher: dict[str, Any] = {"rule": rule, "compiled": None}
            if rule["pattern_type"] == "regex":
                matcher["compiled"] = re.compile(rule["pattern"], re.IGNORECASE)
            matchers.append(matcher)
        return matchers

    def acknowledge_restored_storage(self, revision: int) -> bool:
        if self.rule_manager is None:
            return False
        try:
            stat = self.rule_manager.storage_path.stat()
        except OSError:
            return False
        with self._lock:
            if self.user_rules_revision != revision:
                return False
            self._user_file_signature = (stat.st_mtime_ns, stat.st_size)
            self.reload_error_code = None
            self._reload_blocked = False
        return True

    def enter_degraded_mode(self) -> None:
        with self._lock:
            self._reload_blocked = True
            self.reload_error_code = "USER_RULE_TRANSACTION_DEGRADED"
    def is_user_overlay_detection(self, detection: Detection) -> bool:
        return (
            type(detection) is _UserOverlayDetection
            and detection._owner_token is self._overlay_token
        )
    def user_overlay_metadata(self, detection: Detection) -> dict[str, Any] | None:
        """Return trusted metadata only for this filter's active overlay snapshot."""
        if not self.is_user_overlay_detection(detection):
            return None
        with self._lock:
            active = any(
                matcher["rule"]["id"] == detection._rule_id
                and matcher["rule"]["enabled"] is True
                and matcher["rule"]["action"] == detection._configured_action
                and detection._rule_revision == self.user_rules_revision
                for matcher in self._user_matchers
            )
            if not active:
                return None
        return {
            "rule_source": "user_overlay",
            "configured_action": detection._configured_action,
            "rule_id": detection._rule_id,
            "rule_revision": detection._rule_revision,
        }
    def detect(self, text: str) -> list[Detection]:
        self.reload_if_changed()
        detections: list[Detection] = []
        for category, words in self.words.items():
            matched = [word for word in words if word in text]
            if matched:
                detections.append(
                    Detection(
                        category=category,
                        level="high" if category in {"porn", "violence"} else "medium",
                        score=80 if category in {"porn", "violence"} else 55,
                        reason=f"matched {category} keyword lexicon",
                        source="keyword",
                        matches=matched,
                    )
                )
        for rule, compiled in self._compiled_builtin_regex:
            matches = list(
                dict.fromkeys(match.group(0) for match in compiled.finditer(text))
            )
            if matches:
                detections.append(
                    Detection(
                        category=rule.get("category", "unknown"),
                        level=rule.get("level", "medium"),
                        score=int(rule.get("score", 60)),
                        reason=rule.get("reason", "matched regex rule"),
                        source="regex",
                        matches=matches,
                    )
                )
        with self._lock:
            user_matchers = self._user_matchers
            user_rules_revision = self.user_rules_revision
        for matcher in user_matchers:
            rule = matcher["rule"]
            pattern = rule["pattern"]
            if rule["pattern_type"] == "regex":
                matches = list(
                    dict.fromkeys(
                        match.group(0)
                        for match in matcher["compiled"].finditer(text)
                    )
                )
            else:
                matches = [pattern] if pattern in text else []
            if matches:
                detections.append(
                    _UserOverlayDetection(
                        owner_token=self._overlay_token,
                        rule_id=rule["id"],
                        configured_action=rule["action"],
                        rule_revision=user_rules_revision,
                        category=rule["category"],
                        level=rule["risk_level"],
                        score={"low": 30, "medium": 60, "high": 75}[
                            rule["risk_level"]
                        ],
                        matches=matches,
                    )
                )
        return detections
