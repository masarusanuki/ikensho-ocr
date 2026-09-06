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
import urllib.request
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


# LLMモデルの取得状況（画面に進捗を返すために持つ）
_download = dict(name="", status="idle", received=0, total=0, message="")
_download_lock = threading.Lock()


def _model_dir() -> str:
    return os.path.join(ROOT, "models")


# 医療機関一覧の取得状況
_hosp = dict(status="idle", message="", bureau="", prefs=0, total=0, updated="")
_hosp_lock = threading.Lock()


def _hospital_dir() -> str:
    return os.path.join(ROOT, "dict", "hospitals")


def _hospital_index() -> dict:
    """今持っている医療機関一覧の状況。"""
    path = os.path.join(_hospital_dir(), "index.json")
    try:
        with open(path, encoding="utf-8") as fh:
            idx = json.load(fh)
    except Exception:
        return dict(prefectures=[], total=0, updated="", as_of="")
    prefs = idx.get("prefectures", [])
    days = sorted({p.get("as_of", "") for p in prefs} - {""})
    return dict(prefectures=prefs, total=sum(p.get("count", 0) for p in prefs),
                updated=idx.get("updated", ""),
                as_of=(days[-1] if days else ""),
                errors=idx.get("errors", []))


def _fetch_hospitals(bureaus=None):
    """厚生労働省から医療機関一覧を取り直す。進捗は _hosp に書き込む。

    `bureaus` を渡すと、その地方厚生局だけを取り直す。
    """
    import importlib.util
    path = os.path.join(ROOT, "tools", "fetch_hospitals.py")
    with _hosp_lock:
        _hosp.update(status="running", message="取得を始めます", bureau="",
                     prefs=0, total=0)
    try:
        spec = importlib.util.spec_from_file_location("fetch_hospitals", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        seen_prefs, total = set(), 0

        def on_progress(info):
            nonlocal total
            if info.get("pref"):
                seen_prefs.add(info["pref"])
                total += int(info.get("count") or 0)
            with _hosp_lock:
                _hosp.update(bureau=info.get("bureau", ""),
                             message=info.get("message", ""),
                             prefs=len(seen_prefs), total=total)

        result = mod.run(bureaus or None, out_dir=_hospital_dir(), verbose=False,
                         progress=on_progress)
        copied = _publish_hospitals()
        idx = _hospital_index()
        msg = f"{result['prefectures']} 都道府県 / {result['total']:,} 件を取得しました"
        if result.get("errors"):
            msg += f"（{len(result['errors'])} 件の警告あり）"
        if not copied:
            msg += "。配信フォルダには反映していません（ビルドし直してください）"
        with _hosp_lock:
            _hosp.update(status="done", message=msg,
                         prefs=result["prefectures"], total=result["total"],
                         updated=idx.get("updated", ""))
    except Exception as exc:
        with _hosp_lock:
            _hosp.update(status="error", message=f"取得に失敗しました: {exc}")


def _publish_hospitals() -> bool:
    """取り直した一覧を、配信しているフォルダにも反映する。"""
    dst = os.path.join(_web_root(), "data", "dict", "hospitals")
    if not os.path.isdir(os.path.dirname(dst)):
        return False
    import shutil
    os.makedirs(dst, exist_ok=True)
    for name in os.listdir(_hospital_dir()):
        if name.endswith(".json"):
            shutil.copy2(os.path.join(_hospital_dir(), name),
                         os.path.join(dst, name))
    return True


def _model_choices():
    """選べるモデルの一覧。tools/fetch_llm_model.py の定義を使う。"""
    import importlib.util
    path = os.path.join(ROOT, "tools", "fetch_llm_model.py")
    spec = importlib.util.spec_from_file_location("fetch_llm_model", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.CHOICES


def _download_model(key: str):
    """モデルを取得する。進捗は _download に書き込む。"""
    choices = _model_choices()
    if key not in choices:
        with _download_lock:
            _download.update(status="error", message="そのモデルは選べません")
        return
    fname, url, note = choices[key]
    os.makedirs(_model_dir(), exist_ok=True)
    dst = os.path.join(_model_dir(), fname)
    tmp = dst + ".part"
    with _download_lock:
        _download.update(name=key, status="running", received=0, total=0, message=note)
    try:
        with urllib.request.urlopen(url, timeout=60) as res, open(tmp, "wb") as fp:
            total = int(res.headers.get("Content-Length") or 0)
            with _download_lock:
                _download["total"] = total
            got = 0
            while True:
                chunk = res.read(1024 * 512)
                if not chunk:
                    break
                fp.write(chunk)
                got += len(chunk)
                with _download_lock:
                    _download["received"] = got
        os.replace(tmp, dst)
        with _download_lock:
            _download.update(status="done", message="取得しました。次の読み取りから使われます。")
    except Exception as exc:
        if os.path.exists(tmp):
            os.remove(tmp)
        with _download_lock:
            _download.update(status="error", message=f"取得に失敗しました: {exc}")


def _bureau_names():
    """取得元の地方厚生局の名前（画面の説明に使う）。"""
    return ("北海道", "東北", "関東信越", "東海北陸", "近畿", "中国四国", "四国", "九州")


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
        if path == "/api/models":
            from .llm import LlmAssist, available
            choices = _model_choices()
            installed = os.path.join(ROOT, "models")
            have = set(os.listdir(installed)) if os.path.isdir(installed) else set()
            try:
                import llama_cpp  # noqa: F401
                runtime = True
            except Exception:
                runtime = False
            with _download_lock:
                progress = dict(_download)
            return self._json(dict(
                runtime=runtime,
                enabled=available(),
                current=os.path.basename(LlmAssist._find_model() or ""),
                models=[dict(key=k, file=v[0], note=v[2], installed=v[0] in have)
                        for k, v in choices.items()],
                progress=progress,
            ))
        if path == "/api/hospitals":
            with _hosp_lock:
                progress = dict(_hosp)
            idx = _hospital_index()
            return self._json(dict(
                prefectures=len(idx["prefectures"]),
                total=idx["total"],
                updated=idx["updated"],
                as_of=idx["as_of"],
                bureaus=list(_bureau_names()),
                items=[dict(pref=p.get("pref"), count=p.get("count", 0),
                            as_of=p.get("as_of", "")) for p in idx["prefectures"]],
                progress=progress,
            ))
        if path == "/api/suggest":
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            return self._json(dict(items=Handler.dicts.suggest(
                q.get("field", [""])[0], q.get("q", [""])[0])))
        return super().do_GET()

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/models/download":
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
            with _download_lock:
                if _download["status"] == "running":
                    return self._json(dict(error="すでに取得中です"), 409)
            threading.Thread(target=_download_model, args=(body.get("key", ""),),
                             daemon=True).start()
            return self._json(dict(started=True))
        if path == "/api/hospitals/update":
            length = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except Exception:
                body = {}
            bureaus = [b for b in (body.get("bureaus") or []) if isinstance(b, str)]
            with _hosp_lock:
                if _hosp["status"] == "running":
                    return self._json(dict(error="すでに取得中です"), 409)
            threading.Thread(target=_fetch_hospitals, args=(bureaus,),
                             daemon=True).start()
            return self._json(dict(started=True, bureaus=bureaus or "すべて"))
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


def serve(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True,
          template_dir: Optional[str] = None,
          schema_path: Optional[str] = None) -> None:
    Handler.schema = load_schema(schema_path) if schema_path else load_schema()
    Handler.templates = load_templates(template_dir)
    Handler.dicts = DEFAULT_DICTIONARIES()
    root = _web_root()
    if not os.path.exists(os.path.join(root, "index.html")):
        raise SystemExit("Web ファイルが見つかりません。先に `python tools/build_web.py` を実行してください。")

    with ReusableServer((host, port), Handler) as httpd:
        url = f"http://{host}:{port}/"
        print(f"主治医意見書 読み取り: {url}")
        print(f"  配信元: {root}")
        print(f"  様式テンプレート: {template_dir or os.environ.get('IKENSHO_TEMPLATES') or '(既定)'}"
              f" / {len(Handler.templates)} 種類")
        print(f"  利用可能なOCRエンジン: {', '.join(available_engines())}")
        print("  停止するには Ctrl+C")
        if open_browser:
            threading.Timer(0.8, lambda: webbrowser.open(url)).start()
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n停止しました")
