from __future__ import annotations

import json
import mimetypes
from functools import partial
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .utils import write_text


class ReviewRequestHandler(BaseHTTPRequestHandler):
    server_version = "ShanxiReviewWeb/0.1"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._serve_static("index.html", "text/html; charset=utf-8")
            return
        if parsed.path == "/app.js":
            self._serve_static("app.js", "application/javascript; charset=utf-8")
            return
        if parsed.path == "/styles.css":
            self._serve_static("styles.css", "text/css; charset=utf-8")
            return
        if parsed.path == "/api/manifest":
            self._serve_manifest()
            return
        if parsed.path == "/api/page":
            self._serve_page(parsed.query)
            return
        if parsed.path == "/api/image":
            self._serve_image(parsed.query)
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/save":
            self._save_page()
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def _serve_static(self, filename: str, content_type: str) -> None:
        path = self.server.static_root / filename
        content = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _serve_manifest(self) -> None:
        payload = self.server.manifest_path.read_text(encoding="utf-8")
        data = payload.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_page(self, query: str) -> None:
        params = parse_qs(query)
        book_id = params.get("book_id", [""])[0]
        local_page = int(params.get("local_page", ["0"])[0])
        entry = self.server.page_index.get((book_id, local_page))
        if not entry:
            self.send_error(HTTPStatus.NOT_FOUND, "Page not found")
            return
        markdown = Path(entry["markdown_path"]).read_text(encoding="utf-8")
        payload = dict(entry)
        payload["markdown"] = markdown
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_image(self, query: str) -> None:
        params = parse_qs(query)
        book_id = params.get("book_id", [""])[0]
        local_page = int(params.get("local_page", ["0"])[0])
        entry = self.server.page_index.get((book_id, local_page))
        if not entry:
            self.send_error(HTTPStatus.NOT_FOUND, "Page not found")
            return
        path = Path(entry["image_path"])
        if not path.exists():
            self.send_error(HTTPStatus.NOT_FOUND, "Image not found")
            return
        content = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _save_page(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        book_id = payload["book_id"]
        local_page = int(payload["local_page"])
        markdown = payload["markdown"]
        entry = self.server.page_index.get((book_id, local_page))
        if not entry:
            self.send_error(HTTPStatus.NOT_FOUND, "Page not found")
            return
        write_text(Path(entry["markdown_path"]), markdown)
        data = json.dumps({"ok": True}).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class ReviewHTTPServer(ThreadingHTTPServer):
    def __init__(self, server_address, handler_class, static_root: Path, manifest_path: Path):
        self.static_root = static_root
        self.manifest_path = manifest_path
        manifest_rows = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.page_index = {(row["book_id"], int(row["local_page"])): row for row in manifest_rows}
        super().__init__(server_address, handler_class)


def serve_review_web(context, host: str = "127.0.0.1", port: int = 8765) -> None:
    static_root = Path(__file__).with_name("web")
    handler = ReviewRequestHandler
    server = ReviewHTTPServer((host, port), handler, static_root=static_root, manifest_path=context.work_root / "reports" / "page_review_manifest.json")
    try:
        server.serve_forever()
    finally:
        server.server_close()
