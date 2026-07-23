import json
import socket
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from safechat_guard.pipeline import SafeChatPipeline


ROOT = Path(__file__).resolve().parent
pipeline = SafeChatPipeline.from_config(str(ROOT / "config.yaml"))
API_CONFIG = pipeline.config.get("api", {})
MAX_REQUEST_BYTES = int(API_CONFIG.get("max_request_bytes", 64 * 1024))
MAX_TEXT_CHARS = int(API_CONFIG.get("max_text_chars", 4096))
REQUEST_TIMEOUT_SECONDS = float(API_CONFIG.get("request_timeout_seconds", 10))


def error_payload(code: str, message: str) -> dict:
    return {
        "error": code,
        "message": message,
    }


def detection_to_dict(detection) -> dict:
    return {
        "category": detection.category,
        "level": detection.level,
        "score": detection.score,
        "reason": detection.reason,
        "source": detection.source,
        "matches": detection.matches,
    }


def build_detect_payload(text: str) -> dict:
    normalized = pipeline.normalizer.normalize(text)
    detections = pipeline.semantic_classifier.detect(normalized)
    status = pipeline.semantic_classifier.status()
    return {
        "status": "success",
        "model_loaded": status.get("loaded", False),
        "detections": [detection_to_dict(item) for item in detections],
        "model_error": status.get("error"),
        "model_version": pipeline.semantic_model_version,
        "model_sha256": pipeline.semantic_model_sha256,
        "config_version": pipeline.config.get("app", {}).get("config_version", "unknown"),
        "normalized_text": normalized,
        "semantic_scores": pipeline.semantic_classifier.predict_scores(normalized),
    }


def build_health_payload() -> dict:
    return {
        "status": "ok",
        "service": pipeline.config["app"].get("name", "SafeChat-Guard"),
        "config_version": pipeline.config.get("app", {}).get("config_version", "unknown"),
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
    status = pipeline.semantic_classifier.status()
    llm_status = pipeline.llm.status()
    integrity_configured = bool(status.get("expected_sha256"))
    integrity_ok = status.get("integrity_verified") is True
    classes_configured = bool(status.get("expected_classes"))
    classes_ok = status.get("classes_valid") is True
    ready = bool(
        status.get("loaded")
        and integrity_configured
        and integrity_ok
        and classes_configured
        and classes_ok
        and llm_status.get("ready") is True
    )
    payload = {
        "status": "ready" if ready else "degraded",
        "ready": ready,
        "model_loaded": status.get("loaded", False),
        "model_error": status.get("error"),
        "model_version": pipeline.semantic_model_version,
        "model_sha256": pipeline.semantic_model_sha256,
        "config_version": pipeline.config.get("app", {}).get("config_version", "unknown"),
        "semantic_classifier": status,
        "llm": llm_status,
        "stats": pipeline.stats(),
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

    def _read_json(self) -> tuple[dict | None, str | None]:
        content_type = self.headers.get("Content-Type")
        if content_type and content_type.split(";", 1)[0].strip().lower() != "application/json":
            return None, "unsupported_media_type"
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return None, "invalid_content_length"
        if length < 0 or length > MAX_REQUEST_BYTES:
            return None, "request_too_large"
        try:
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
        except (TimeoutError, socket.timeout):
            return None, "request_timeout"
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
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
                    error_payload("invalid_request", "since must be an ISO-8601 timestamp"),
                    status=422,
                )
                return
            self._send_json(pipeline.stats(since=since))
            return
        self._send_json(error_payload("not_found", "Not found"), status=404)

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

            if parsed.path == "/api/chat":
                message, validation_error = self._validate_text_field(payload, "message")
                if validation_error:
                    code, detail, status = validation_error
                    self._send_json(error_payload(code, detail), status=status)
                    return
                raw_reply_override, validation_error = self._validate_text_field(
                    payload,
                    "raw_reply_override",
                    optional=True,
                )
                if validation_error:
                    code, detail, status = validation_error
                    self._send_json(error_payload(code, detail), status=status)
                    return
                result = pipeline.handle_chat(
                    message,
                    raw_reply_override=raw_reply_override,
                )
                self._send_json(result, status=503 if result.get("service_error") else 200)
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
            self._send_json(
                error_payload("internal_error", "Internal server error"),
                status=500,
            )

    def log_message(self, format: str, *args) -> None:
        return


if __name__ == "__main__":
    host = pipeline.config["app"].get("host", "127.0.0.1")
    port = int(pipeline.config["app"].get("port", 8000))
    print(f"SafeChat-Guard API running at http://{host}:{port}")
    server = ThreadingHTTPServer((host, port), SafeChatApiHandler)
    server.daemon_threads = True
    server.serve_forever()
