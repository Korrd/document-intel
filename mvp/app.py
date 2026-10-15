#!/usr/bin/env python3
"""HTTP server for the demo. Stdlib only, no framework, nothing to install.

Routes
  GET  /                      the UI
  GET  /api/documents         ingested documents + validator status
  GET  /api/document/<id>     one Document Intelligence Record
  GET  /api/crossdoc          cross-document consistency findings
  POST /api/ask               {"question": ..., "doc_ids": [...]} -> grounded answer
  POST /api/ingest            {"path": ...} -> ingest one file
  GET  /api/usage             token + cost accounting
  GET  /page/<file>           page images
  GET  /crop/<file>           crops produced by the escalation path
"""
import json
import pathlib
import socketserver
import sys
import threading
import traceback
import urllib.parse
from http.server import SimpleHTTPRequestHandler

import gateway
import pipeline
import query
import store

ROOT = pathlib.Path(__file__).resolve().parent
STATIC = ROOT / "static"
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8765

_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
         ".html": "text/html; charset=utf-8", ".css": "text/css",
         ".js": "application/javascript", ".json": "application/json"}


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        if "/api/" in (self.path or ""):
            sys.stderr.write("  %s %s\n" % (self.command, self.path))

    # ------------------------------------------------------------- helpers ---
    def _send(self, code, body, ctype="application/json"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False, default=str).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path):
        path = pathlib.Path(path)
        if not path.is_file():
            return self._send(404, {"error": "not found"})
        self._send(200, path.read_bytes(),
                   _MIME.get(path.suffix.lower(), "application/octet-stream"))

    def _safe(self, base, name):
        """Resolve `name` under `base`, refusing anything that escapes it."""
        target = (base / urllib.parse.unquote(name)).resolve()
        if base.resolve() not in target.parents and target != base.resolve():
            return None
        return target

    # ----------------------------------------------------------------- GET ---
    def do_GET(self):
        route = urllib.parse.urlparse(self.path).path
        try:
            if route in ("/", "/index.html"):
                return self._file(STATIC / "index.html")
            if route == "/api/documents":
                return self._send(200, dict(documents=store.list_documents()))
            if route.startswith("/api/document/"):
                rec = store.get_record(route.split("/api/document/", 1)[1])
                return self._send(200 if rec else 404, rec or {"error": "unknown document"})
            if route == "/api/crossdoc":
                return self._send(200, dict(findings=query.cross_document_report()))
            if route == "/api/usage":
                return self._send(200, gateway.usage_report())
            if route.startswith("/page/"):
                p = self._safe(store.PAGES, route.split("/page/", 1)[1])
                return self._file(p) if p else self._send(403, {"error": "forbidden"})
            if route.startswith("/crop/"):
                p = self._safe(store.DATA, route.split("/crop/", 1)[1])
                return self._file(p) if p else self._send(403, {"error": "forbidden"})
            if route.startswith("/static/"):
                p = self._safe(STATIC, route.split("/static/", 1)[1])
                return self._file(p) if p else self._send(403, {"error": "forbidden"})
            return self._send(404, {"error": "no such route"})
        except Exception:
            traceback.print_exc()
            return self._send(500, {"error": traceback.format_exc(limit=2)})

    # ---------------------------------------------------------------- POST ---
    def do_POST(self):
        route = urllib.parse.urlparse(self.path).path
        try:
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return self._send(400, {"error": "invalid JSON body"})
        try:
            if route == "/api/ask":
                q = (payload.get("question") or "").strip()
                if not q:
                    return self._send(400, {"error": "question is required"})
                return self._send(200, query.answer(q, doc_ids=payload.get("doc_ids") or None))
            if route == "/api/ingest":
                path = payload.get("path")
                if not path:
                    return self._send(400, {"error": "path is required"})
                return self._send(200, pipeline.ingest(path, force=payload.get("force", False)))
            return self._send(404, {"error": "no such route"})
        except Exception:
            traceback.print_exc()
            return self._send(500, {"error": traceback.format_exc(limit=3)})


class Server(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    docs = store.list_documents()
    print("Document Intelligence Assistant -- MVP")
    print("  %d document(s) ingested, %d field(s) indexed"
          % (len(docs), len(store.field_names())))
    if not docs:
        print("  no documents yet: run `python3 pipeline.py --reset` first")
    print("  http://localhost:%d" % PORT)
    with Server(("127.0.0.1", PORT), Handler) as httpd:
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            print("\nbye")
