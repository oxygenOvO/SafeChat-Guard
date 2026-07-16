import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from safechat_guard.pipeline import SafeChatPipeline


pipeline = SafeChatPipeline.from_config("config.yaml")
ROOT = Path(__file__).parent
MAX_REQUEST_BYTES = 1_000_000


def parse_json_object(raw: str) -> dict:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("Invalid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("JSON body must be an object")
    return payload


def require_text(payload: dict, field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"'{field}' must be a non-empty string")
    return value


def build_detect_payload(text: str) -> dict:
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    normalized = pipeline.normalizer.normalize(text)
    detections = pipeline.semantic_classifier.detect(normalized)
    status = pipeline.semantic_classifier.status()
    predict_scores = getattr(pipeline.semantic_classifier, "predict_scores", None)
    semantic_scores = predict_scores(normalized) if predict_scores else {}
    return {
        "status": "success",
        "model_loaded": status.get("loaded", False),
        "model_error": status.get("error"),
        "normalized_text": normalized,
        "semantic_scores": semantic_scores,
        "detections": [detection.__dict__ for detection in detections],
    }


class SafeChatHandler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _send_file(self, path: Path, content_type: str) -> None:
        if not path.exists() or not path.is_file():
            self._send(404, b"Not found", "text/plain; charset=utf-8")
            return
        self._send(200, path.read_bytes(), content_type)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send_file(ROOT / "templates" / "index.html", "text/html; charset=utf-8")
            return
        if parsed.path == "/api/stats":
            self._send_json(pipeline.stats())
            return
        if parsed.path == "/static/style.css":
            self._send_file(ROOT / "static" / "style.css", "text/css; charset=utf-8")
            return
        if parsed.path == "/static/app.js":
            self._send_file(ROOT / "static" / "app.js", "application/javascript; charset=utf-8")
            return
        self._send(404, b"Not found", "text/plain; charset=utf-8")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path not in {"/api/chat", "/api/detect"}:
            self._send(404, b"Not found", "text/plain; charset=utf-8")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0 or length > MAX_REQUEST_BYTES:
                self._send_json({"error": "Request body too large"}, status=413)
                return
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            payload = parse_json_object(raw)
            if parsed.path == "/api/chat":
                result = pipeline.handle_chat(require_text(payload, "message"))
            else:
                result = build_detect_payload(require_text(payload, "text"))
        except (UnicodeDecodeError, ValueError) as exc:
            self._send_json({"error": str(exc)}, status=400)
            return
        self._send_json(result)

    def log_message(self, format: str, *args) -> None:
        return


if __name__ == "__main__":
    host = pipeline.config["app"].get("host", "127.0.0.1")
    port = int(pipeline.config["app"].get("port", 8000))
    print(f"SafeChat-Guard running at http://{host}:{port}")
    ThreadingHTTPServer((host, port), SafeChatHandler).serve_forever()
