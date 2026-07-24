import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from safechat_guard.pipeline import SafeChatPipeline
from safechat_guard.semantic_classifier import SemanticClassifier


pipeline = SafeChatPipeline.from_config("config.yaml")
semantic_classifier = SemanticClassifier(model_path="models/semantic_model.pkl")
ROOT = Path(__file__).parent


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
        
        # 原有 /api/chat 接口（完整流水线）
        if parsed.path == "/api/chat":
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                self._send_json({"error": "Invalid JSON"}, status=400)
                return
            result = pipeline.handle_chat(payload.get("message", ""))
            self._send_json(result)
            return

        # 新增 /api/detect 接口（纯语义分类）
        if parsed.path == "/api/detect":
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                self._send_json({"error": "Invalid JSON"}, status=400)
                return

            text = payload.get("text", "")
            if not text:
                self._send_json({"error": "Missing 'text' field"}, status=400)
                return

            detections = semantic_classifier.detect(text)
            status_info = semantic_classifier.status()

            results = []
            for d in detections:
                results.append({
                    "category": d.category,
                    "level": d.level,
                    "score": d.score,
                    "reason": d.reason,
                    "source": d.source,
                    "matches": d.matches
                })

            self._send_json({
                "status": "success",
                "model_loaded": status_info.get("loaded", False),
                "detections": results,
                "model_error": status_info.get("error")
            })
            return

        self._send(404, b"Not found", "text/plain; charset=utf-8")

    def log_message(self, format: str, *args) -> None:
        return


if __name__ == "__main__":
    host = pipeline.config["app"].get("host", "127.0.0.1")
    port = int(pipeline.config["app"].get("port", 8000))
    print(f"SafeChat-Guard running at http://{host}:{port}")
    ThreadingHTTPServer((host, port), SafeChatHandler).serve_forever()