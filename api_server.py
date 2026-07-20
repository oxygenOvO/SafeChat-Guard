import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from safechat_guard.pipeline import SafeChatPipeline


ROOT = Path(__file__).resolve().parent
MAX_REQUEST_BYTES = 64 * 1024
pipeline = SafeChatPipeline.from_config(str(ROOT / "config.yaml"))


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
        "normalized_text": normalized,
        "semantic_scores": pipeline.semantic_classifier.predict_scores(normalized),
    }


class SafeChatApiHandler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _read_json(self) -> tuple[dict | None, str | None]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return None, "Invalid Content-Length"
        if length < 0 or length > MAX_REQUEST_BYTES:
            return None, "Request body is too large"
        raw = self.rfile.read(length).decode("utf-8") if length else "{}"
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None, "Invalid JSON"
        if not isinstance(payload, dict):
            return None, "JSON body must be an object"
        return payload, None

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/stats":
            self._send_json(pipeline.stats())
            return
        self._send(404, b"Not found", "text/plain; charset=utf-8")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        payload, error = self._read_json()
        if error:
            status = 413 if error == "Request body is too large" else 400
            self._send_json({"error": error}, status=status)
            return

        if parsed.path == "/api/chat":
            message = payload.get("message")
            if not isinstance(message, str) or not message.strip():
                self._send_json({"error": "Missing or invalid 'message' field"}, status=400)
                return
            try:
                result = pipeline.handle_chat(
                    message,
                    raw_reply_override=payload.get("raw_reply_override"),
                )
            except TypeError as exc:
                self._send_json({"error": str(exc)}, status=400)
                return
            self._send_json(result)
            return

        if parsed.path == "/api/detect":
            text = payload.get("text")
            if not isinstance(text, str) or not text.strip():
                self._send_json({"error": "Missing or invalid 'text' field"}, status=400)
                return
            self._send_json(build_detect_payload(text))
            return

        self._send(404, b"Not found", "text/plain; charset=utf-8")

    def log_message(self, format: str, *args) -> None:
        return


if __name__ == "__main__":
    host = pipeline.config["app"].get("host", "127.0.0.1")
    port = int(pipeline.config["app"].get("api_port", 8000))
    print(f"SafeChat-Guard API running at http://{host}:{port}")
    ThreadingHTTPServer((host, port), SafeChatApiHandler).serve_forever()
