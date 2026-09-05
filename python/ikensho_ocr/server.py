# -*- coding: utf-8 -*-
"""ローカルWebサーバ。

確認・編集画面（web/）をそのまま配信し、あわせてサーバ側で読み取る API を提供する。
ブラウザだけで完結させたい場合は web/ を任意のサーバに置くだけでよく、
このサーバは「Python 側の高精度OCRを使いたい場合」や「オフラインで手軽に起動したい場合」向け。
"""
import http.server
import json
import os
import socketserver
import tempfile
import threading
import urllib.parse
import webbrowser
from typing import Optional

from .dictionaries import DEFAULT_DICTIONARIES
from .export import csv_text, record_to_json
from .extract import extract_record
from .ocr import available_engines
from .schema import load_schema
from .templates import load_templates

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WEB_DIR = os.path.join(ROOT, "dist", "web")
FALLBACK_WEB = os.path.join(ROOT, "web")
MAX_UPLOAD = 80 * 1024 * 1024


def _web_root() -> str:
    if os.path.isdir(WEB_DIR) and os.path.exists(os.path.join(WEB_DIR, "index.html")):
        return WEB_DIR
    return FALLBACK_WEB


class Handler(http.server.SimpleHTTPRequestHandler):
    schema = None
    templates = None
    dicts = None

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=_web_root(), **kw)

    def log_message(self, fmt, *args):
        pass    # 静かに動かす

    # ------------------------------------------------------------- API
    def _json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/info":
            return self._json(dict(
                schema_version=Handler.schema.version,
                fields=len(Handler.schema.order),
                templates=[dict(id=t.id, name=t.name, pages=t.page_count,
                                boxes=sum(len(p.boxes) for p in t.pages),
                                texts=sum(len(p.texts) for p in t.pages))
                           for t in Handler.templates.values()],
                ocr_engines=available_engines(),
                dictionaries={k: len(v.entries)
                              for k, v in Handler.dicts.lexicons.items()},
            ))
        if path == "/api/suggest":
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            return self._json(dict(items=Handler.dicts.suggest(
                q.get("field", [""])[0], q.get("q", [""])[0])))
        return super().do_GET()

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if path != "/api/extract":
            return self._json(dict(error="not found"), 404)
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_UPLOAD:
            return self._json(dict(error="アップロードサイズが不正です"), 400)

        ctype = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in ctype:
            return self._json(dict(error="multipart/form-data で送信してください"), 400)

        import email.parser
        raw = b"Content-Type: " + ctype.encode() + b"\r\n\r\n" + self.rfile.read(length)
        msg = email.parser.BytesParser().parsebytes(raw)

        with tempfile.TemporaryDirectory() as td:
            paths = []
            for part in msg.walk():
                if part.get_content_maintype() == "multipart":
                    continue
                name = part.get_filename()
                if not name:
                    continue
                safe = os.path.basename(name).replace("..", "_")
                p = os.path.join(td, safe)
                with open(p, "wb") as fp:
                    fp.write(part.get_payload(decode=True) or b"")
                paths.append(p)
            if not paths:
                return self._json(dict(error="ファイルがありません"), 400)
            rec = extract_record(paths, schema=Handler.schema,
                                 templates=Handler.templates,
                                 dictionaries=Handler.dicts)
            return self._json(record_to_json(rec, Handler.schema))


class ReusableServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def serve(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> None:
    Handler.schema = load_schema()
    Handler.templates = load_templates()
    Handler.dicts = DEFAULT_DICTIONARIES()
    root = _web_root()
    if not os.path.exists(os.path.join(root, "index.html")):
        raise SystemExit("Web ファイルが見つかりません。先に `python tools/build_web.py` を実行してください。")

    with ReusableServer((host, port), Handler) as httpd:
        url = f"http://{host}:{port}/"
        print(f"主治医意見書 読み取り: {url}")
        print(f"  配信元: {root}")
        print(f"  利用可能なOCRエンジン: {', '.join(available_engines())}")
        print("  停止するには Ctrl+C")
        if open_browser:
            threading.Timer(0.8, lambda: webbrowser.open(url)).start()
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n停止しました")
