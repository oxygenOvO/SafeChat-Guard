from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import os
import socket
import warnings
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse


from safechat_guard.pipeline import SafeChatPipeline
from safechat_guard.logger import StatisticsValidationError
from safechat_guard.rule_manager import (
    RuleConflictError,
    RuleImportTooLargeError,
    RuleManagerError,
    RuleNotFoundError,
    RuleStorageError,
    RuleValidationError,
    apply_rule_transaction,
)

def dispatch_management_get(handler: Any, parsed: Any, pipeline: Any) -> bool:
    if parsed.path in {"/api/stats/summary", "/api/stats/daily"}:
        from urllib.parse import parse_qs

        params = parse_qs(parsed.query)
        try:
            stats = pipeline.logger.daily_stats(
                start_date=_one(params, "start_date"),
                end_date=_one(params, "end_date"),
                timezone_name=_one(params, "timezone"),
            )
        except StatisticsValidationError as exc:
            handler._send_json(
                {"error": "invalid_request", "message": str(exc)}, status=400
            )
            return True
        if parsed.path.endswith("/daily"):
            stats = {
                "source": stats["source"],
                "timezone": stats["timezone"],
                "start_date": stats["start_date"],
                "end_date": stats["end_date"],
                "request_count": stats["request_count"],
                "violation_count": stats["violation_count"],
                "daily_violation_counts": stats["daily_violation_counts"],
                "category_distribution": stats["category_distribution"],
            }
        handler._send_json(stats)
        return True

    if parsed.path == "/api/rules" or parsed.path.startswith("/api/rules/"):
        try:
            include_pattern = _include_pattern_requested(parsed)
        except RuleValidationError as exc:
            handler._send_json(
                {"error": exc.code, "message": str(exc)}, status=400
            )
            return True
        if include_pattern and not _admin_authorized(handler):
            handler._send_json(
                {"error": "forbidden", "message": "Rule management access denied"},
                status=403,
            )
            return True
        if parsed.path == "/api/rules":
            handler._send_json(
                _rules_payload(pipeline, include_pattern=include_pattern)
            )
            return True
        prefix = "/api/rules/"
        rule_id = unquote(parsed.path[len(prefix):])
        if not rule_id or "/" in rule_id:
            return False
        rule = _find_public_rule(
            pipeline, rule_id, include_pattern=include_pattern
        )
        if rule is None:
            handler._send_json(
                {"error": "not_found", "message": "Rule not found"}, status=404
            )
        else:
            handler._send_json({"rule": rule, **pipeline.rule_manager.metadata()})
        return True
    return False


def dispatch_management_write(
    handler: Any,
    method: str,
    parsed: Any,
    payload: dict[str, Any],
    pipeline: Any,
) -> bool:
    path = parsed.path
    if not (
        path == "/api/rules"
        or path.startswith("/api/rules/")
    ):
        return False
    if not _admin_authorized(handler):
        handler._send_json(
            {"error": "forbidden", "message": "Rule management access denied"},
            status=403,
        )
        return True

    manager = pipeline.rule_manager
    try:
        if method == "POST" and path == "/api/rules":
            expected = payload.pop("expected_revision", None)
            rule_id = payload.get("id") if isinstance(payload.get("id"), str) else None
            result = _run_rule_mutation(
                pipeline,
                "rule_created",
                rule_id,
                lambda: manager.add_rule(
                    payload, expected_revision=expected, source="manual"
                ),
            )
            handler._send_json(_public_management_result(result), status=201)
            return True

        if method == "POST" and path in {
            "/api/rules/import",
            "/api/rules/validate-import",
        }:
            allowed = {
                "format", "content", "mode", "dry_run", "expected_revision"
            }
            unknown = set(payload) - allowed
            if unknown:
                raise RuleValidationError(
                    "unknown field is not allowed"
                )
            format_name = payload.get("format")
            content = payload.get("content")
            mode = payload.get("mode", "create")
            dry_run = (
                True
                if path.endswith("validate-import")
                else payload.get("dry_run", False)
            )
            if not isinstance(dry_run, bool):
                raise RuleValidationError("dry_run must be a boolean")
            importer = (
                manager.import_csv
                if format_name == "csv"
                else manager.import_json
                if format_name == "json"
                else None
            )
            if importer is None:
                raise RuleValidationError("format must be csv or json")
            mutation = lambda: importer(
                content,
                dry_run=dry_run,
                mode=mode,
                expected_revision=payload.get("expected_revision"),
            )
            result = (
                mutation()
                if dry_run
                else _run_rule_mutation(
                    pipeline, "rule_imported", None, mutation
                )
            )
            handler._send_json(_public_management_result(result))
            return True

        prefix = "/api/rules/"
        if not path.startswith(prefix):
            return False
        suffix = unquote(path[len(prefix):])
        operation = None
        if suffix.endswith("/enable"):
            rule_id, operation = suffix[:-7], "enable"
        elif suffix.endswith("/disable"):
            rule_id, operation = suffix[:-8], "disable"
        else:
            rule_id = suffix
        if not rule_id or "/" in rule_id:
            raise RuleNotFoundError("rule does not exist")
        if rule_id.startswith("builtin:"):
            raise RuleConflictError("built-in rules are read-only")
        expected = payload.get("expected_revision")

        if method == "PATCH" and operation is None:
            changes = dict(payload)
            changes.pop("expected_revision", None)
            mutation = lambda: manager.update_rule(
                rule_id, changes, expected_revision=expected
            )
            event = "rule_updated"
        elif method == "POST" and operation == "enable":
            _only_expected_revision(payload)
            mutation = lambda: manager.enable_rule(
                rule_id, expected_revision=expected
            )
            event = "rule_enabled"
        elif method == "POST" and operation == "disable":
            _only_expected_revision(payload)
            mutation = lambda: manager.disable_rule(
                rule_id, expected_revision=expected
            )
            event = "rule_disabled"
        elif method == "DELETE" and operation is None:
            _only_expected_revision(payload)
            mutation = lambda: manager.delete_rule(
                rule_id, expected_revision=expected
            )
            event = "rule_deleted"
        else:
            return False
        result = _run_rule_mutation(pipeline, event, rule_id, mutation)
        handler._send_json(_public_management_result(result))
        return True
    except RuleManagerError as exc:
        status = _error_status(exc)
        message = (
            "Rule storage operation failed"
            if isinstance(exc, RuleStorageError)
            else str(exc)
        )
        response: dict[str, Any] = {"error": exc.code, "message": message}
        if isinstance(exc.details, dict):
            response["details"] = exc.details
        handler._send_json(response, status=status)
        return True


def _include_pattern_requested(parsed: Any) -> bool:
    values = parse_qs(parsed.query).get("include_pattern")
    if values is None:
        return False
    if len(values) != 1 or values[0] not in {"true", "false"}:
        raise RuleValidationError("include_pattern must be true or false")
    return values[0] == "true"


def _public_rule(rule: dict[str, Any], *, include_pattern: bool) -> dict[str, Any]:
    public = dict(rule)
    public["pattern_redacted"] = not include_pattern
    if not include_pattern:
        public["pattern"] = "[REDACTED]"
    return public


def _public_management_result(result: dict[str, Any]) -> dict[str, Any]:
    public = dict(result)
    if isinstance(public.get("rule"), dict):
        public["rule"] = _public_rule(public["rule"], include_pattern=False)
    return public


def _rules_payload(pipeline: Any, *, include_pattern: bool = False) -> dict[str, Any]:
    builtins = _builtin_rules(pipeline, include_pattern=include_pattern)
    users = [
        {
            **_public_rule(rule, include_pattern=include_pattern),
            "origin": "user",
            "read_only": False,
        }
        for rule in pipeline.rule_manager.list_rules()
    ]
    return {
        "rules": [*builtins, *users],
        "built_in_count": len(builtins),
        "user_count": len(users),
        **pipeline.rule_manager.metadata(),
    }


def _builtin_rules(
    pipeline: Any, *, include_pattern: bool = False
) -> list[dict[str, Any]]:
    rows = []
    for category, words in sorted(pipeline.rule_filter.words.items()):
        for index, word in enumerate(words):
            rows.append(
                _public_rule(
                    {
                        "id": f"builtin:keyword:{category}:{index}",
                        "pattern": word,
                        "pattern_type": "keyword",
                        "category": category,
                        "action": "block" if category in {"porn", "violence"} else "sanitize",
                        "risk_level": "high" if category in {"porn", "violence"} else "medium",
                        "enabled": True,
                        "description": "Built-in keyword rule",
                        "source": "builtin",
                        "origin": "builtin",
                        "read_only": True,
                    },
                    include_pattern=include_pattern,
                )
            )
    for index, rule in enumerate(pipeline.rule_filter.regex_rules):
        rows.append(
            _public_rule(
                {
                    "id": f"builtin:regex:{index}",
                    "pattern": rule.get("pattern", ""),
                    "pattern_type": "regex",
                    "category": rule.get("category", "sensitive"),
                    "action": "block" if int(rule.get("score", 60)) >= 80 else "sanitize",
                    "risk_level": rule.get("level", "medium"),
                    "enabled": True,
                    "description": rule.get("reason", "Built-in regex rule"),
                    "source": "builtin",
                    "origin": "builtin",
                    "read_only": True,
                },
                include_pattern=include_pattern,
            )
        )
    return rows


def _find_public_rule(
    pipeline: Any, rule_id: str, *, include_pattern: bool = False
) -> dict[str, Any] | None:
    if rule_id.startswith("builtin:"):
        return next(
            (
                rule
                for rule in _builtin_rules(
                    pipeline, include_pattern=include_pattern
                )
                if rule["id"] == rule_id
            ),
            None,
        )
    try:
        return {
            **_public_rule(
                pipeline.rule_manager.get_rule(rule_id),
                include_pattern=include_pattern,
            ),
            "origin": "user",
            "read_only": False,
        }
    except RuleNotFoundError:
        return None


def _run_rule_mutation(
    pipeline: Any,
    operation: str,
    rule_id: str | None,
    mutation: Any,
) -> dict[str, Any]:
    try:
        result = apply_rule_transaction(
            pipeline.rule_manager, pipeline.rule_filter, mutation
        )
    except RuleManagerError:
        _audit(pipeline, operation, rule_id, pipeline.rule_manager.revision, "failed")
        raise
    _audit(pipeline, operation, rule_id, result["revision"], "success")
    return result

def _admin_authorized(handler: Any) -> bool:
    configured = os.getenv("SAFECHAT_RULE_ADMIN_TOKEN")
    if configured:
        supplied = handler.headers.get("X-Admin-Token", "")
        authorization = handler.headers.get("Authorization", "")
        if authorization.startswith("Bearer "):
            supplied = authorization[7:]
        return bool(supplied) and hmac.compare_digest(supplied, configured)
    try:
        return ipaddress.ip_address(handler.client_address[0]).is_loopback
    except (AttributeError, ValueError):
        return False



def _audit(
    pipeline: Any,
    operation: str,
    rule_id: str | None,
    revision: int,
    result: str = "success",
) -> None:
    try:
        pipeline.logger.write(
            {
                "stage": "rule_management",
                "operation": operation,
                "rule_id": rule_id,
                "revision": revision,
                "result": result,
            }
        )
    except Exception:
        warnings.warn(
            "rule management audit logging failed",
            RuntimeWarning,
            stacklevel=2,
        )


def _only_expected_revision(payload: dict[str, Any]) -> None:
    unknown = set(payload) - {"expected_revision"}
    if unknown:
        raise RuleValidationError("unknown field is not allowed")


def _error_status(exc: RuleManagerError) -> int:
    if isinstance(exc, RuleImportTooLargeError):
        return 413
    if isinstance(exc, RuleNotFoundError):
        return 404
    if isinstance(exc, RuleConflictError):
        return 409
    if isinstance(exc, RuleValidationError):
        return 400
    return 500


def _one(params: dict[str, list[str]], name: str) -> str | None:
    values = params.get(name)
    if not values:
        return None
    if len(values) != 1:
        raise StatisticsValidationError(f"{name} must be provided once")
    return values[0]


ROOT = Path(__file__).resolve().parent
pipeline = SafeChatPipeline.from_config(str(ROOT / "config.yaml"))
API_CONFIG = pipeline.config.get("api", {})
MAX_REQUEST_BYTES = int(API_CONFIG.get("max_request_bytes", 64 * 1024))
MAX_TEXT_CHARS = int(API_CONFIG.get("max_text_chars", 4096))
REQUEST_TIMEOUT_SECONDS = float(API_CONFIG.get("request_timeout_seconds", 10))


def error_payload(code: str, message: str) -> dict:
    return {"error": code, "message": message}


def build_detect_payload(text: str) -> dict:
    result = pipeline.detect_text(text)
    semantic_status = pipeline.stats(portable_paths=True)["semantic_classifier"]
    return {
        "status": "success",
        "model_loaded": semantic_status.get("loaded", False),
        "model_error": semantic_status.get("error"),
        "normalized_text": result["normalized_text"],
        "action": result["action"],
        "risk_score": result["risk_score"],
        "risk_level": result["risk_level"],
        "risk_categories": result["risk_categories"],
        "detections": result["detections"],
    }


def _sha256_if_file(path: Path | None) -> str | None:
    if path is None or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _v3_artifact_hashes() -> dict[str, str | None]:
    configured = pipeline.config.get("action_v3", {}).get(
        "threshold_config_path", "config/action_thresholds_v3.json"
    )
    threshold_path = Path(configured)
    if not threshold_path.is_absolute():
        threshold_path = pipeline.project_root / threshold_path
    threshold_sha256 = _sha256_if_file(threshold_path)
    try:
        payload = json.loads(threshold_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        payload = {}

    def configured_model_hash(field: str) -> str | None:
        value = payload.get(field)
        if not isinstance(value, str) or not value:
            return None
        path = Path(value)
        if not path.is_absolute():
            path = pipeline.project_root / path
        return _sha256_if_file(path)

    return {
        "risk_model_sha256": configured_model_hash("risk_model_path"),
        "block_model_sha256": configured_model_hash("block_model_path"),
        "threshold_config_sha256": threshold_sha256,
    }


def build_health_payload() -> dict:
    router = pipeline.action_router_v3
    models = getattr(router, "models", None)
    risk_model_loaded = bool(
        models is not None and getattr(models, "risk_model", None) is not None
    )
    block_model_loaded = bool(
        models is not None and getattr(models, "block_model", None) is not None
    )
    v3_enabled = bool(pipeline.action_router_v3_enabled)
    v3_ready = bool(
        v3_enabled and router is not None and risk_model_loaded and block_model_loaded
    )
    fallback_active = bool(v3_enabled and not v3_ready)
    return {
        "status": "ok",
        "service": pipeline.config["app"].get("name", "SafeChat-Guard"),
        "active_filter_version": "v3" if v3_ready else "v2",
        "v3_enabled": v3_enabled,
        "v3_ready": v3_ready,
        "risk_model_loaded": risk_model_loaded,
        "block_model_loaded": block_model_loaded,
        "fallback_active": fallback_active,
        "fallback_reason": (
            pipeline.action_router_v3_error_code or "v3_unavailable"
            if fallback_active
            else None
        ),
        **_v3_artifact_hashes(),
    }


def parse_since(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def build_ready_payload() -> tuple[dict, int]:
    stats = pipeline.stats(portable_paths=True)
    semantic_status = stats["semantic_classifier"]
    llm_status = pipeline.llm.status()
    semantic_ready = bool(
        semantic_status.get("loaded") or not semantic_status.get("required", False)
    )
    ready = bool(semantic_ready and llm_status.get("ready") is True)
    payload = {
        "status": "ready" if ready else "degraded",
        "ready": ready,
        "semantic_classifier": semantic_status,
        "llm": llm_status,
        "stats": stats,
    }
    return payload, 200 if ready else 503


class SafeChatApiHandler(BaseHTTPRequestHandler):
    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(REQUEST_TIMEOUT_SECONDS)

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _send_internal_error(self) -> None:
        try:
            self._send_json(
                error_payload("internal_error", "Internal server error"), status=500
            )
        except (BrokenPipeError, ConnectionResetError, OSError):
            return

    def _read_json(self) -> tuple[dict | None, str | None]:
        content_type = self.headers.get("Content-Type")
        if (
            content_type
            and content_type.split(";", 1)[0].strip().lower() != "application/json"
        ):
            return None, "unsupported_media_type"
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return None, "invalid_content_length"
        if length < 0 or length > MAX_REQUEST_BYTES:
            return None, "request_too_large"
        try:
            raw_bytes = self.rfile.read(length) if length else b"{}"
            raw = raw_bytes.decode("utf-8")
            payload = json.loads(raw)
        except (TimeoutError, socket.timeout):
            return None, "request_timeout"
        except UnicodeDecodeError:
            return None, "invalid_encoding"
        except json.JSONDecodeError:
            return None, "invalid_json"
        if not isinstance(payload, dict):
            return None, "invalid_json_body"
        return payload, None

    @staticmethod
    def _validate_text_field(
        payload: dict,
        field: str,
        *,
        optional: bool = False,
    ) -> tuple[str | None, tuple[str, str, int] | None]:
        value = payload.get(field)
        if optional and value is None:
            return None, None
        if not isinstance(value, str) or not value.strip():
            return None, (
                "invalid_request",
                f"{field} must be a non-empty string",
                422,
            )
        if len(value) > MAX_TEXT_CHARS:
            return None, (
                "text_too_long",
                f"{field} exceeds the maximum of {MAX_TEXT_CHARS} characters",
                413,
            )
        return value, None

    def do_GET(self) -> None:
        try:
            parsed = urlparse(self.path)
            if parsed.path == "/health":
                self._send_json(build_health_payload())
                return
            if parsed.path == "/ready":
                payload, status = build_ready_payload()
                self._send_json(payload, status=status)
                return
            if parsed.path == "/api/stats":
                try:
                    since = parse_since(parse_qs(parsed.query).get("since", [None])[0])
                except ValueError:
                    self._send_json(
                        error_payload(
                            "invalid_request", "since must be an ISO-8601 timestamp"
                        ),
                        status=422,
                    )
                    return
                self._send_json(pipeline.stats(since=since, portable_paths=True))
                return
            if dispatch_management_get(self, parsed, pipeline):
                return
            self._send_json(error_payload("not_found", "Not found"), status=404)
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception:
            self._send_internal_error()

    def do_POST(self) -> None:
        try:
            parsed = urlparse(self.path)
            payload, error = self._read_json()
            if error:
                messages = {
                    "invalid_content_length": "Invalid Content-Length",
                    "request_too_large": "Request body is too large",
                    "request_timeout": "Request body read timed out",
                    "unsupported_media_type": "Content-Type must be application/json",
                    "invalid_encoding": "Request body must be UTF-8",
                    "invalid_json": "Invalid JSON",
                    "invalid_json_body": "JSON body must be an object",
                }
                statuses = {
                    "request_too_large": 413,
                    "request_timeout": 408,
                    "unsupported_media_type": 415,
                }
                self._send_json(
                    error_payload(error, messages.get(error, error)),
                    status=statuses.get(error, 400),
                )
                return

            if dispatch_management_write(self, "POST", parsed, payload, pipeline):
                return

            if parsed.path == "/api/chat":
                message, validation_error = self._validate_text_field(payload, "message")
                if validation_error:
                    code, detail, status = validation_error
                    self._send_json(error_payload(code, detail), status=status)
                    return
                raw_reply_override, validation_error = self._validate_text_field(
                    payload, "raw_reply_override", optional=True
                )
                if validation_error:
                    code, detail, status = validation_error
                    self._send_json(error_payload(code, detail), status=status)
                    return
                result = pipeline.handle_chat(
                    message, raw_reply_override=raw_reply_override
                )
                self._send_json(
                    result, status=503 if result.get("service_error") else 200
                )
                return

            if parsed.path == "/api/detect":
                text, validation_error = self._validate_text_field(payload, "text")
                if validation_error:
                    code, detail, status = validation_error
                    self._send_json(error_payload(code, detail), status=status)
                    return
                self._send_json(build_detect_payload(text))
                return

            self._send_json(error_payload("not_found", "Not found"), status=404)
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception:
            self._send_internal_error()

    def _management_mutation(self, method: str) -> None:
        try:
            parsed = urlparse(self.path)
            payload, error = self._read_json()
            if error:
                status = 413 if error == "request_too_large" else 400
                self._send_json(
                    error_payload(error, "Invalid request body"), status=status
                )
                return
            if dispatch_management_write(self, method, parsed, payload, pipeline):
                return
            self._send_json(error_payload("not_found", "Not found"), status=404)
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception:
            self._send_internal_error()

    def do_PATCH(self) -> None:
        self._management_mutation("PATCH")

    def do_DELETE(self) -> None:
        self._management_mutation("DELETE")
    def log_message(self, format: str, *args) -> None:
        return


def create_server(
    host: str | None = None,
    port: int | None = None,
) -> ThreadingHTTPServer:
    configured_host = pipeline.config["app"].get("host", "127.0.0.1")
    configured_port = int(pipeline.config["app"].get("port", 8000))
    server = ThreadingHTTPServer(
        (host or configured_host, configured_port if port is None else port),
        SafeChatApiHandler,
    )
    server.daemon_threads = True
    return server


def main() -> None:
    server = create_server()
    host, port = server.server_address[:2]
    print(f"SafeChat-Guard API running at http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
