"""用户自定义规则的持久化管理器（CRUD + 事务 + 回滚）。

负责用户规则的完整生命周期：
- 校验：pattern 类型（keyword/phrase/regex）、类别、动作、风险等级、
  正则可编译性、冲突检测等，非法规则一律拒绝入库；
- 存储：规则写入独立 JSON 文件，带版本号（revision）与内容哈希（sha256），
  每次"读-改-写"都用乐观锁校验版本，防止并发修改互相覆盖；
- 事务：``apply_rule_transaction``（由 rule_manager/管理服务使用）保证
  "候选编译 → 原子落盘 → 内存快照激活" 三步一致，任一步失败自动回滚；
- 备份与回滚：``rollback_to_backup`` 可恢复上一版规则集；
- 导入：支持 UTF-8 CSV/JSON 批量导入，限制大小并做逐行校验。

注意：本模块只管"用户规则"；系统内置词库/正则由 RuleFilter 直接加载，
内置规则的展示动作策略统一定义在 rule_management_service 中。
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import shutil
import tempfile
import threading
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


# 用户规则允许的取值空间（内置词库不受此限制）
PATTERN_TYPES = {"keyword", "phrase", "regex"}
CATEGORIES = {"porn", "violence", "ad", "sensitive"}
ACTIONS = {"sanitize", "block"}
RISK_LEVELS = {"low", "medium", "high"}
SOURCES = {"manual", "csv_import", "json_import"}
IMPORT_FIELDS = {
    "id",
    "pattern",
    "pattern_type",
    "category",
    "action",
    "risk_level",
    "enabled",
    "description",
}
STORED_FIELDS = IMPORT_FIELDS | {"created_at", "updated_at", "source"}
MAX_PATTERN_LENGTH = 512
MAX_DESCRIPTION_LENGTH = 1000
MAX_IMPORT_BYTES = 1024 * 1024
MAX_IMPORT_RULES = 1000
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
NESTED_QUANTIFIER = re.compile(
    r"\((?:[^()\\]|\\.)*[*+](?:[^()\\]|\\.)*\)\s*(?:[*+{])"
)


class RuleManagerError(Exception):
    code = "rule_manager_error"

    def __init__(self, message: str, *, details: Any = None):
        super().__init__(message)
        self.details = details


class RuleValidationError(RuleManagerError):
    code = "validation_error"


class RuleNotFoundError(RuleManagerError):
    code = "not_found"


class RuleConflictError(RuleManagerError):
    code = "conflict"


class RuleImportTooLargeError(RuleManagerError):
    code = "import_too_large"


class RuleStorageError(RuleManagerError):
    code = "storage_error"


class RuleManager:
    """Thread-safe manager for the mutable user-rule overlay."""

    FORMAT_VERSION = 1

    def __init__(self, storage_path: str | Path):
        self.storage_path = Path(storage_path).resolve()
        self.backup_path = self.storage_path.with_suffix(
            self.storage_path.suffix + ".bak"
        )
        self._lock = threading.RLock()
        self._state: dict[str, Any] = {}
        self._candidate_validator: Callable[[list[dict[str, Any]], int], None] | None = None
        self._degraded = False
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.storage_path.exists():
            self._atomic_write(self._empty_state())
        self.reload()

    @staticmethod
    def default_path(project_root: str | Path) -> Path:
        return Path(project_root).resolve() / "data" / "rules" / "user_rules.json"

    def reload(self) -> dict[str, Any]:
        with self._lock:
            state = self._read_state()
            self._state = state
            return self.metadata()

    def metadata(self) -> dict[str, Any]:
        with self._lock:
            return {
                "version": self._state["version"],
                "revision": self._state["revision"],
                "content_sha256": self._state["content_sha256"],
                "rule_count": len(self._state["rules"]),
            }

    @property
    def revision(self) -> int:
        with self._lock:
            return int(self._state["revision"])

    @property
    def degraded(self) -> bool:
        with self._lock:
            return self._degraded

    def set_candidate_validator(
        self,
        validator: Callable[[list[dict[str, Any]], int], None],
    ) -> None:
        if not callable(validator):
            raise TypeError("candidate validator must be callable")
        with self._lock:
            self._candidate_validator = validator

    def snapshot_state(self) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._state)

    def restore_snapshot(self, snapshot: dict[str, Any]) -> None:
        """Atomically restore a previously trusted state, including its revision."""
        with self._lock:
            restored = deepcopy(snapshot)
            self._atomic_write(restored)
            self._state = restored
            self._degraded = False

    def restore_memory_snapshot(self, snapshot: dict[str, Any]) -> None:
        with self._lock:
            self._state = deepcopy(snapshot)

    def enter_degraded_mode(self) -> None:
        with self._lock:
            self._degraded = True

    def list_rules(self, *, enabled_only: bool = False) -> list[dict[str, Any]]:
        with self._lock:
            rules = self._state["rules"]
            if enabled_only:
                rules = [rule for rule in rules if rule["enabled"]]
            return deepcopy(rules)

    def get_rule(self, rule_id: str) -> dict[str, Any]:
        with self._lock:
            index = self._find_index(rule_id)
            return deepcopy(self._state["rules"][index])

    def add_rule(
        self,
        rule: dict[str, Any],
        *,
        expected_revision: int | None = None,
        source: str = "manual",
    ) -> dict[str, Any]:
        with self._lock:
            self._prepare_write(expected_revision)
            normalized = self._normalize_rule(rule, source=source)
            if any(item["id"] == normalized["id"] for item in self._state["rules"]):
                raise RuleConflictError("rule id already exists")
            state = deepcopy(self._state)
            state["rules"].append(normalized)
            self._commit(state)
            return {"rule": deepcopy(normalized), **self.metadata()}

    def update_rule(
        self,
        rule_id: str,
        changes: dict[str, Any],
        *,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            self._prepare_write(expected_revision)
            index = self._find_index(rule_id)
            if not isinstance(changes, dict):
                raise RuleValidationError("changes must be an object")
            disallowed = set(changes) - (
                IMPORT_FIELDS - {"id"}
            )
            if disallowed:
                raise RuleValidationError(
                    "unknown or immutable field"
                )
            candidate = {
                key: value
                for key, value in self._state["rules"][index].items()
                if key in IMPORT_FIELDS
            }
            candidate.update(changes)
            candidate["id"] = rule_id
            normalized = self._normalize_rule(
                candidate,
                source=self._state["rules"][index]["source"],
                created_at=self._state["rules"][index]["created_at"],
            )
            state = deepcopy(self._state)
            state["rules"][index] = normalized
            self._commit(state)
            return {"rule": deepcopy(normalized), **self.metadata()}

    def enable_rule(
        self, rule_id: str, *, expected_revision: int | None = None
    ) -> dict[str, Any]:
        return self.update_rule(
            rule_id, {"enabled": True}, expected_revision=expected_revision
        )

    def disable_rule(
        self, rule_id: str, *, expected_revision: int | None = None
    ) -> dict[str, Any]:
        return self.update_rule(
            rule_id, {"enabled": False}, expected_revision=expected_revision
        )

    def delete_rule(
        self, rule_id: str, *, expected_revision: int | None = None
    ) -> dict[str, Any]:
        with self._lock:
            self._prepare_write(expected_revision)
            index = self._find_index(rule_id)
            state = deepcopy(self._state)
            state["rules"].pop(index)
            self._commit(state)
            return {"deleted": rule_id, **self.metadata()}

    def validate_import(
        self,
        content: str | bytes,
        *,
        format: str,
        mode: str = "create",
    ) -> dict[str, Any]:
        raw = self._decode_import(content)
        if not isinstance(format, str) or format not in {"csv", "json"}:
            raise RuleValidationError("format must be csv or json")
        if not isinstance(mode, str) or mode not in {"create", "update"}:
            raise RuleValidationError("mode must be create or update")
        records = self._parse_csv(raw) if format == "csv" else self._parse_json(raw)
        if len(records) > MAX_IMPORT_RULES:
            raise RuleImportTooLargeError("import contains too many rules")

        existing = {rule["id"] for rule in self.list_rules()}
        seen: set[str] = set()
        valid_rules: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        duplicates = 0
        source = f"{format}_import"
        for position, record in enumerate(records, start=1):
            rule_id = record.get("id") if isinstance(record, dict) else None
            try:
                normalized = self._normalize_rule(record, source=source)
                if normalized["id"] in seen:
                    duplicates += 1
                    raise RuleConflictError("duplicate id in import")
                if mode == "create" and normalized["id"] in existing:
                    duplicates += 1
                    raise RuleConflictError("rule id already exists")
                if mode == "update" and normalized["id"] not in existing:
                    raise RuleNotFoundError("update target does not exist")
                seen.add(normalized["id"])
                valid_rules.append(normalized)
            except RuleManagerError as exc:
                errors.append(
                    {
                        "row": position,
                        "rule_id": self._safe_rule_id(rule_id),
                        "code": exc.code,
                        "message": str(exc),
                    }
                )
        return {
            "format": format,
            "mode": mode,
            "total": len(records),
            "valid": len(valid_rules),
            "invalid": len(errors),
            "duplicate": duplicates,
            "errors": errors,
            "_rules": valid_rules,
        }

    def import_csv(
        self,
        content: str | bytes,
        *,
        dry_run: bool = False,
        mode: str = "create",
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        return self._import(
            content,
            format="csv",
            dry_run=dry_run,
            mode=mode,
            expected_revision=expected_revision,
        )

    def import_json(
        self,
        content: str | bytes,
        *,
        dry_run: bool = False,
        mode: str = "create",
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        return self._import(
            content,
            format="json",
            dry_run=dry_run,
            mode=mode,
            expected_revision=expected_revision,
        )

    def _import(
        self,
        content: str | bytes,
        *,
        format: str,
        dry_run: bool,
        mode: str,
        expected_revision: int | None,
    ) -> dict[str, Any]:
        if not isinstance(dry_run, bool):
            raise RuleValidationError("dry_run must be a boolean")
        with self._lock:
            self._prepare_write(expected_revision)
            report = self.validate_import(content, format=format, mode=mode)
            public_report = {key: value for key, value in report.items() if key != "_rules"}
            public_report["dry_run"] = bool(dry_run)
            if report["invalid"]:
                if dry_run:
                    return {**public_report, **self.metadata()}
                raise RuleValidationError(
                    "import validation failed", details=public_report
                )
            if dry_run:
                return {**public_report, **self.metadata()}

            state = deepcopy(self._state)
            if mode == "create":
                state["rules"].extend(report["_rules"])
            else:
                existing = {rule["id"]: rule for rule in state["rules"]}
                replacements = {}
                for imported in report["_rules"]:
                    replacement = dict(imported)
                    replacement["created_at"] = existing[imported["id"]]["created_at"]
                    replacement["updated_at"] = self._now()
                    replacements[imported["id"]] = replacement
                state["rules"] = [
                    replacements.get(rule["id"], rule) for rule in state["rules"]
                ]
            self._commit(state)
            return {**public_report, "imported": report["valid"], **self.metadata()}

    def backup_snapshot(self) -> dict[str, Any] | None:
        """Return the validated previous on-disk revision, when available."""
        with self._lock:
            if not self.backup_path.is_file():
                return None
            return deepcopy(self._read_state(self.backup_path))

    def rollback_to_backup(
        self, *, expected_revision: int | None = None
    ) -> dict[str, Any]:
        """Publish the previous revision as a new monotonic revision."""
        with self._lock:
            self._prepare_write(expected_revision)
            backup = self.backup_snapshot()
            if backup is None:
                raise RuleNotFoundError("backup revision does not exist")
            state = deepcopy(backup)
            self._commit(state)
            return {"rolled_back_from": backup["revision"], **self.metadata()}

    def _read_state(self, path: Path | None = None) -> dict[str, Any]:
        source_path = path or self.storage_path
        try:
            raw = json.loads(source_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RuleStorageError("user rule storage is unavailable") from exc
        if not isinstance(raw, dict):
            raise RuleStorageError("user rule storage root must be an object")
        if set(raw) != {"version", "revision", "content_sha256", "rules"}:
            raise RuleStorageError("user rule storage has invalid fields")
        if (
            isinstance(raw["version"], bool)
            or not isinstance(raw["version"], int)
            or raw["version"] != self.FORMAT_VERSION
        ):
            raise RuleStorageError("unsupported user rule storage version")
        if isinstance(raw["revision"], bool) or not isinstance(raw["revision"], int):
            raise RuleStorageError("user rule storage revision must be an integer")
        if raw["revision"] < 0 or not isinstance(raw["rules"], list):
            raise RuleStorageError("user rule storage structure is invalid")
        normalized = []
        for item in raw["rules"]:
            try:
                normalized.append(self._normalize_stored_rule(item))
            except RuleValidationError as exc:
                raise RuleStorageError("user rule storage contains an invalid rule") from exc
        expected_sha = self._rules_sha(normalized)
        if raw["content_sha256"] != expected_sha:
            raise RuleStorageError("user rule storage checksum mismatch")
        return {
            "version": self.FORMAT_VERSION,
            "revision": raw["revision"],
            "content_sha256": expected_sha,
            "rules": normalized,
        }

    def _commit(self, state: dict[str, Any]) -> None:
        state["version"] = self.FORMAT_VERSION
        state["revision"] = self._state["revision"] + 1
        state["rules"] = sorted(state["rules"], key=lambda item: item["id"])
        state["content_sha256"] = self._rules_sha(state["rules"])
        if self._candidate_validator is not None:
            try:
                self._candidate_validator(
                    deepcopy(state["rules"]), int(state["revision"])
                )
            except RuleManagerError:
                raise
            except Exception as exc:
                raise RuleValidationError(
                    "candidate user rules failed validation"
                ) from exc
        self._atomic_write(state)
        self._state = state

    def _atomic_write(self, state: dict[str, Any]) -> None:
        serialized = json.dumps(state, ensure_ascii=False, indent=2) + "\n"
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.storage_path.parent,
                prefix=".user-rules-",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temp_path = Path(handle.name)
                handle.write(serialized)
                handle.flush()
                os.fsync(handle.fileno())
            if self.storage_path.exists():
                shutil.copy2(self.storage_path, self.backup_path)
            os.replace(temp_path, self.storage_path)
        except OSError as exc:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass
            raise RuleStorageError("unable to persist user rules") from exc

    def _empty_state(self) -> dict[str, Any]:
        return {
            "version": self.FORMAT_VERSION,
            "revision": 0,
            "content_sha256": self._rules_sha([]),
            "rules": [],
        }

    def _normalize_stored_rule(self, rule: Any) -> dict[str, Any]:
        if not isinstance(rule, dict) or set(rule) != STORED_FIELDS:
            raise RuleValidationError("stored rule fields are invalid")
        created = rule.get("created_at")
        updated = rule.get("updated_at")
        source = rule.get("source")
        self._validate_timestamp(created, "created_at")
        self._validate_timestamp(updated, "updated_at")
        if not isinstance(source, str) or source not in SOURCES:
            raise RuleValidationError("source is invalid")
        base = {key: rule[key] for key in IMPORT_FIELDS}
        return self._normalize_rule(
            base, source=source, created_at=created, updated_at=updated
        )

    def _normalize_rule(
        self,
        rule: Any,
        *,
        source: str,
        created_at: str | None = None,
        updated_at: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(rule, dict):
            raise RuleValidationError("rule must be an object")
        unknown = set(rule) - IMPORT_FIELDS
        missing = IMPORT_FIELDS - set(rule)
        if unknown:
            raise RuleValidationError("unknown field is not allowed")
        if missing:
            raise RuleValidationError(f"missing field: {sorted(missing)[0]}")
        rule_id = rule["id"]
        if not isinstance(rule_id, str) or not ID_PATTERN.fullmatch(rule_id):
            raise RuleValidationError("id has an invalid format")
        pattern = rule["pattern"]
        if not isinstance(pattern, str) or not pattern.strip():
            raise RuleValidationError("pattern must be a non-empty string")
        pattern = pattern.strip()
        if len(pattern) > MAX_PATTERN_LENGTH:
            raise RuleValidationError("pattern is too long")
        pattern_type = rule["pattern_type"]
        if not isinstance(pattern_type, str) or pattern_type not in PATTERN_TYPES:
            raise RuleValidationError("pattern_type is invalid")
        if not isinstance(rule["category"], str) or rule["category"] not in CATEGORIES:
            raise RuleValidationError("category is invalid")
        if not isinstance(rule["action"], str) or rule["action"] not in ACTIONS:
            raise RuleValidationError("action is invalid")
        if not isinstance(rule["risk_level"], str) or rule["risk_level"] not in RISK_LEVELS:
            raise RuleValidationError("risk_level is invalid")
        if not isinstance(rule["enabled"], bool):
            raise RuleValidationError("enabled must be a boolean")
        description = rule["description"]
        if not isinstance(description, str):
            raise RuleValidationError("description must be a string")
        if len(description) > MAX_DESCRIPTION_LENGTH:
            raise RuleValidationError("description is too long")
        if description.startswith(("=", "+", "-", "@")):
            raise RuleValidationError("description has an unsafe spreadsheet prefix")
        if not isinstance(source, str) or source not in SOURCES:
            raise RuleValidationError("source is invalid")
        if pattern_type == "regex":
            self._validate_regex(pattern)
        now = self._now()
        return {
            "id": rule_id,
            "pattern": pattern,
            "pattern_type": pattern_type,
            "category": rule["category"],
            "action": rule["action"],
            "risk_level": rule["risk_level"],
            "enabled": rule["enabled"],
            "description": description,
            "created_at": created_at or now,
            "updated_at": updated_at or now,
            "source": source,
        }

    @staticmethod
    def _validate_regex(pattern: str) -> None:
        if len(pattern) > 256:
            raise RuleValidationError("regex is too long")
        if NESTED_QUANTIFIER.search(pattern):
            raise RuleValidationError("regex contains a nested quantifier")
        if re.search(r"\((?:[^()\\]|\\.)*\|(?:[^()\\]|\\.)*\)\s*(?:[*+{])", pattern):
            raise RuleValidationError("regex contains a quantified alternation")
        if re.search(r"(?:\.\*|\.\+).*(?:\.\*|\.\+)", pattern):
            raise RuleValidationError("regex contains repeated wildcards")
        if re.search(r"\\[1-9]", pattern):
            raise RuleValidationError("regex backreferences are not allowed")
        try:
            re.compile(pattern, re.IGNORECASE)
        except re.error as exc:
            raise RuleValidationError("regex does not compile") from exc

    def _find_index(self, rule_id: str) -> int:
        if not isinstance(rule_id, str) or not ID_PATTERN.fullmatch(rule_id):
            raise RuleNotFoundError("rule does not exist")
        for index, rule in enumerate(self._state["rules"]):
            if rule["id"] == rule_id:
                return index
        raise RuleNotFoundError("rule does not exist")

    def _prepare_write(self, expected_revision: int | None) -> None:
        # Refresh first so sequential writers in different API/UI processes observe
        # the latest committed revision before optimistic-concurrency validation.
        self._state = self._read_state()
        if self._degraded:
            raise RuleStorageError("user rule manager is in degraded mode")
        self._check_revision(expected_revision)
    def _check_revision(self, expected_revision: int | None) -> None:
        if expected_revision is None:
            return
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int):
            raise RuleValidationError("expected_revision must be an integer")
        if expected_revision != self._state["revision"]:
            raise RuleConflictError("revision conflict")

    @staticmethod
    def _rules_sha(rules: list[dict[str, Any]]) -> str:
        payload = json.dumps(
            rules, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    @staticmethod
    def _decode_import(content: str | bytes) -> str:
        if isinstance(content, str):
            raw = content.encode("utf-8")
            text = content
        elif isinstance(content, bytes):
            raw = content
            try:
                text = content.decode("utf-8-sig")
            except UnicodeDecodeError as exc:
                raise RuleValidationError("import must use UTF-8") from exc
        else:
            raise RuleValidationError("content must be text or bytes")
        if len(raw) > MAX_IMPORT_BYTES:
            raise RuleImportTooLargeError("import is too large")
        return text.lstrip("\ufeff")

    @staticmethod
    def _parse_csv(content: str) -> list[dict[str, Any]]:
        try:
            reader = csv.DictReader(io.StringIO(content, newline=""))
            if reader.fieldnames is None or set(reader.fieldnames) != IMPORT_FIELDS:
                raise RuleValidationError("CSV header is invalid")
            records = []
            for row in reader:
                if None in row:
                    raise RuleValidationError("CSV row has too many columns")
                normalized = dict(row)
                enabled = str(normalized["enabled"]).strip().lower()
                if enabled not in {"true", "false"}:
                    normalized["enabled"] = enabled
                else:
                    normalized["enabled"] = enabled == "true"
                records.append(normalized)
            return records
        except csv.Error as exc:
            raise RuleValidationError("CSV is malformed") from exc

    @staticmethod
    def _parse_json(content: str) -> list[dict[str, Any]]:
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as exc:
            raise RuleValidationError("JSON is malformed") from exc
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict) and set(payload) == {"rules"}:
            if isinstance(payload["rules"], list):
                return payload["rules"]
        raise RuleValidationError("JSON must be an array or an object containing rules")

    @staticmethod
    def _safe_rule_id(value: Any) -> str | None:
        if isinstance(value, str) and ID_PATTERN.fullmatch(value):
            return value
        return None

    @staticmethod
    def _validate_timestamp(value: Any, field: str) -> None:
        if not isinstance(value, str):
            raise RuleValidationError(f"{field} must be a timestamp")
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise RuleValidationError(f"{field} must be a timestamp") from exc
        if parsed.tzinfo is None:
            raise RuleValidationError(f"{field} must include a timezone")

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()


def apply_rule_transaction(
    manager: RuleManager,
    rule_filter: Any,
    mutation: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    """Commit a rule mutation and activate it as one observable transaction."""
    if manager.degraded:
        raise RuleStorageError("user rule manager is in degraded mode")
    try:
        baseline_ready = rule_filter.reload_user_rules(force=True)
    except Exception as exc:
        raise RuleStorageError("unable to prepare user rule transaction") from exc
    if not baseline_ready:
        raise RuleStorageError("unable to prepare user rule transaction")

    snapshot = manager.snapshot_state()
    result = mutation()
    try:
        activated = rule_filter.reload_user_rules(force=True)
    except Exception:
        activated = False
    if activated:
        return result

    try:
        manager.restore_snapshot(snapshot)
        restored = rule_filter.acknowledge_restored_storage(
            int(snapshot["revision"])
        )
        if not restored:
            raise RuleStorageError("unable to restore user rule snapshot")
    except Exception as rollback_error:
        manager.restore_memory_snapshot(snapshot)
        manager.enter_degraded_mode()
        try:
            rule_filter.enter_degraded_mode()
        except Exception:
            pass
        raise RuleStorageError(
            "user rule transaction failed and entered degraded mode"
        ) from rollback_error
    raise RuleStorageError("user rule transaction was rolled back")
