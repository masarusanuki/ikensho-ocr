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

from . import gennai as gennai_mod
from . import labels as labels_mod
from .dictionaries import DEFAULT_DICTIONARIES
from .export import csv_text, record_to_form_json, record_to_json
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


# VLM は1つのモデルを使い回すので、同時に走らせない
_vlm_lock = threading.Lock()

# LLMモデルの取得状況（画面に進捗を返すために持つ）
_download = dict(name="", status="idle", received=0, total=0, message="")
_download_lock = threading.Lock()


def _model_dir() -> str:
    return os.path.join(ROOT, "models")


# 日本語OCRモデルの取得状況
_ocr = dict(key="", status="idle", received=0, total=0, message="")
_ocr_lock = threading.Lock()


def _ocr_tool():
    """tools/fetch_ocr_model.py を読み込む（選べるモデルの定義がある）。"""
    import importlib.util
    path = os.path.join(ROOT, "tools", "fetch_ocr_model.py")
    spec = importlib.util.spec_from_file_location("fetch_ocr_model", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _publish_ocr_models() -> bool:
    """取ったモデルを、ブラウザ版が読む場所にも置く。

    ブラウザには**認識モデルと文字辞書だけ**を渡す（欄の位置は分かっているので
    検出モデルは使わない）。大きい server 版は重すぎるので渡さない。
    """
    from .ocr import MODEL_PREFERENCE, installed_ocr_models
    dst_root = os.path.join(_web_root(), "data", "ocr")
    if not os.path.isdir(os.path.dirname(dst_root)):
        return False
    import shutil
    os.makedirs(dst_root, exist_ok=True)
    models = [m for m in installed_ocr_models() if "server" not in m["key"]]
    order = {k: i for i, k in enumerate(MODEL_PREFERENCE)}
    models.sort(key=lambda m: order.get(m["key"], 99))
    models = models[:1]                     # いちばん良いものだけを配る
    listed = []
    for m in models:
        base = os.path.join(dst_root, m["key"])
        os.makedirs(base, exist_ok=True)
        for src in (m["rec"], m["keys"]):
            target = os.path.join(base, os.path.basename(src))
            if not os.path.exists(target):
                shutil.copy2(src, target)
        listed.append(dict(key=m["key"], note=m["note"],
                           rec=os.path.basename(m["rec"]),
                           keys=os.path.basename(m["keys"]),
                           bytes=os.path.getsize(m["rec"])))
    with open(os.path.join(dst_root, "index.json"), "w", encoding="utf-8") as fh:
        json.dump({"models": listed}, fh, ensure_ascii=False, indent=1)
    return True


def _download_ocr_model(key: str):
    """日本語OCRモデルを取得する。進捗は _ocr に書き込む。"""
    mod = _ocr_tool()
    if key not in mod.CHOICES:
        with _ocr_lock:
            _ocr.update(status="error", message="そのモデルは選べません")
        return
    with _ocr_lock:
        _ocr.update(key=key, status="running", received=0, total=0,
                    message=mod.CHOICES[key]["note"])
    try:
        conf = mod.CHOICES[key]
        base = os.path.join(mod.OUT_DIR, key)
        os.makedirs(base, exist_ok=True)
        for part in ("rec", "keys", "det"):
            if part not in conf:
                continue
            repo, name = conf[part]
            dst = os.path.join(base, name)
            if os.path.exists(dst) and os.path.getsize(dst) > 1024:
                continue
            url = mod.url_for(repo, name)
            req = urllib.request.Request(url, headers={"User-Agent": mod.UA})
            tmp = dst + ".part"
            with urllib.request.urlopen(req, timeout=180) as res, open(tmp, "wb") as fp:
                total = int(res.headers.get("Content-Length") or 0)
                with _ocr_lock:
                    _ocr.update(total=total, received=0, message=f"{part}: {name}")
                got = 0
                while True:
                    chunk = res.read(1024 * 256)
                    if not chunk:
                        break
                    fp.write(chunk)
                    got += len(chunk)
                    with _ocr_lock:
                        _ocr["received"] = got
            os.replace(tmp, dst)
        mod.fetch(key, mod.OUT_DIR, verbose=False)     # model.json を書く
        published = _publish_ocr_models()
        msg = "取得しました。次の読み取りから使われます。"
        if published:
            msg += "ブラウザ版は画面を再読み込みしてください。"
        with _ocr_lock:
            _ocr.update(status="done", message=msg)
    except Exception as exc:
        with _ocr_lock:
            _ocr.update(status="error", message=f"取得に失敗しました: {exc}")


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
    vlm_name = ""
    # 源内（デジタル庁の生成AI基盤）の AI アプリとして応答するか。
    # **既定は無効。** 患者情報が端末の外に出るため、明示したときだけ開く
    gennai = False
    # 別の場所に置いたページから API を呼ばせたい場合だけ、明示的に許す。
    # 既定は空＝同じ場所のページからしか使えない（勝手に画像を送られないため）
    allow_origins: list = []
    dicts = None

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=_web_root(), **kw)

    def log_message(self, fmt, *args):
        pass    # 静かに動かす

    # ------------------------------------------------------------- API
    def _cors(self):
        """許した場所からの呼び出しにだけ、越境を許可する見出しを付ける。

        既定では何も付けない。付けると**どのページからでも画像を送れる**ため、
        `--allow-origin` で明示された場所だけに限る。
        """
        origin = self.headers.get("Origin")
        if not origin or not Handler.allow_origins:
            return
        if "*" in Handler.allow_origins or origin in Handler.allow_origins:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def do_OPTIONS(self):
        """越境呼び出しの事前確認（プリフライト）に答える。"""
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._cors()
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
        if path == "/api/ocr-models":
            from .ocr import MODEL_PREFERENCE, get_engine, installed_ocr_models
            mod = _ocr_tool()
            have = {m["key"]: m for m in installed_ocr_models()}
            with _ocr_lock:
                progress = dict(_ocr)
            order = {k: i for i, k in enumerate(MODEL_PREFERENCE)}
            models = [dict(key=k, note=v["note"], installed=k in have,
                           bytes=(os.path.getsize(have[k]["rec"])
                                  if k in have else 0))
                      for k, v in mod.CHOICES.items()]
            models.sort(key=lambda m: order.get(m["key"], 99))
            return self._json(dict(
                current=getattr(get_engine("auto"), "name", "none"),
                models=models, progress=progress,
                measured="docs/developer.html#h20",
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
        if path == "/api/labels":
            # チェック欄の後ろの言葉。定義のものと、直したものを返す
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            tid = q.get("template", ["official_v1"])[0]
            return self._json(dict(template=tid,
                                   overrides=labels_mod.load_overrides(tid)))
        if path == "/api/gennai/form":
            # 源内の「リクエスト形式」に貼り付ける JSON を返す（登録作業用）
            if not Handler.gennai:
                return self._json(dict(error="源内向けの受け口は無効です"
                                             "（ikensho serve --gennai で開きます）"), 404)
            return self._json(gennai_mod.REQUEST_FORM)
        if path == "/api/vlm":
            # VLM（画像を見て読むLLM）が使えるか。ブラウザ版の切り替えボタン用
            try:
                from . import vlm as vlm_mod
                models = vlm_mod.installed_models()
                return self._json(dict(
                    available=bool(models), models=[
                        dict(key=m["key"], size_mb=m["size_mb"]) for m in models],
                    loaded=Handler.vlm_name,
                    note="画像はこの端末のPythonに渡すだけで、外部には出ません",
                ))
            except Exception as exc:
                return self._json(dict(available=False, models=[], error=str(exc)))
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
        if path == "/api/ocr-models/download":
            length = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except Exception:
                body = {}
            with _ocr_lock:
                if _ocr["status"] == "running":
                    return self._json(dict(error="すでに取得中です"), 409)
            threading.Thread(target=_download_ocr_model,
                             args=(body.get("key", ""),), daemon=True).start()
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
        if path == "/api/labels":
            # チェック欄の後ろの言葉を直す。{"template": ..., "labels": {...}}
            length = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except Exception:
                body = {}
            tid = str(body.get("template") or "")
            if not tid or tid not in Handler.templates:
                return self._json(dict(error="知らない様式です"), 400)
            got = body.get("labels")
            if not isinstance(got, dict):
                return self._json(dict(error="labels がありません"), 400)
            path_saved = labels_mod.save_overrides(tid, got)
            return self._json(dict(saved=os.path.basename(path_saved),
                                   count=len(labels_mod.load_overrides(tid))))
        if path == "/api/vlm-read":
            return self._vlm_read()
        if path == "/api/gennai":
            return self._gennai()
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


    # ---------------------------------------------------------- 源内向け
    def _gennai(self):
        """源内（デジタル庁の生成AI基盤）の AI アプリとして1通を読む。

        取り決めは genai-web の「AI アプリ API 仕様」に合わせてある。
          受け取り {"inputs": {...}} / 返し {"outputs": "Markdown"}
        """
        if not Handler.gennai:
            return self._json(dict(error="源内向けの受け口は無効です"
                                         "（ikensho serve --gennai で開きます）"), 404)
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_UPLOAD:
            return self._json(dict(error="送信サイズが不正です"), 400)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            return self._json(dict(error="JSON を読めません"), 400)
        inputs = body.get("inputs")
        if not isinstance(inputs, dict):
            return self._json(dict(error="inputs がありません"), 400)
        try:
            files = gennai_mod.parse_files(inputs)
        except gennai_mod.GennaiError as exc:
            return self._json(dict(error=str(exc)), 400)
        opt = gennai_mod.options(inputs)

        with tempfile.TemporaryDirectory() as td:
            paths = []
            for name, blob in files:
                p = os.path.join(td, name)
                with open(p, "wb") as fp:
                    fp.write(blob)
                paths.append(p)
            try:
                rec = extract_record(paths, schema=Handler.schema,
                                     templates=Handler.templates,
                                     dictionaries=Handler.dicts,
                                     anonymized=opt["anonymized"])
            except Exception as exc:
                return self._json(dict(error=f"読み取りに失敗しました（{exc}）"), 500)
        form = record_to_form_json(rec, Handler.schema)
        if opt["format"] == "json":
            text = json.dumps(form, ensure_ascii=False, indent=2)
            return self._json(dict(outputs=f"```json\n{text}\n```"))
        return self._json(dict(outputs=gennai_mod.to_markdown(form)))

    # ------------------------------------------------------------ VLM
    def _vlm_read(self):
        """1欄ぶんの切り抜き画像を VLM で読む。

        ブラウザ版から呼ぶ。画像はこの端末の Python プロセスに渡すだけで、
        外部には出ない（LLM もローカルで動かす）。
        """
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > 8 * 1024 * 1024:
            return self._json(dict(error="画像の大きさが不正です"), 400)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            return self._json(dict(error="JSON を読めません"), 400)
        data = str(body.get("image") or "")
        if "," in data:
            data = data.split(",", 1)[1]
        try:
            import base64
            import cv2
            import numpy as np
            buf = np.frombuffer(base64.b64decode(data), dtype=np.uint8)
            img = cv2.imdecode(buf, cv2.IMREAD_GRAYSCALE)
        except Exception as exc:
            return self._json(dict(error=f"画像を読めません（{exc}）"), 400)
        if img is None or img.size == 0:
            return self._json(dict(error="画像が空です"), 400)
        try:
            from . import vlm as vlm_mod
            with _vlm_lock:            # モデルは1つしか無いので順番に使う
                eng = vlm_mod.get_engine(body.get("model") or None)
                if not getattr(eng, "available", False):
                    return self._json(dict(error="VLM が使えません"
                                                 "（tools/fetch_vlm_model.py で取得してください）"), 503)
                Handler.vlm_name = eng.name
                res = eng.read(img, multiline=bool(body.get("multiline")),
                               charset=str(body.get("charset") or ""))
        except Exception as exc:
            return self._json(dict(error=f"VLM の読み取りに失敗しました（{exc}）"), 500)
        return self._json(dict(text=res.text, confidence=res.confidence,
                               engine=res.engine))


class ReusableServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def serve(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True,
          template_dir: Optional[str] = None,
          schema_path: Optional[str] = None,
          allow_origins: Optional[list] = None,
          gennai: bool = False) -> None:
    Handler.allow_origins = [o.strip() for o in (allow_origins or []) if o.strip()]
    Handler.gennai = bool(gennai)
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
        if Handler.gennai:
            print("  源内向けの受け口を開きました: POST /api/gennai")
            print("    登録用のリクエスト形式: GET /api/gennai/form")
            print("    ** 送られた意見書はこの端末で読みますが、"
                  "源内はクラウド上のサービスです。")
            print("    ** 要配慮個人情報を端末の外に出してよいか、"
                  "運用の取り決めを必ず確かめてください。")
        if Handler.allow_origins:
            print("  別の場所のページからの呼び出しを許しました: "
                  + "、".join(Handler.allow_origins))
            print("    （許した場所のページは、この端末の読み取りAPIを使えます）")
        print("  停止するには Ctrl+C")
        if open_browser:
            threading.Timer(0.8, lambda: webbrowser.open(url)).start()
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n停止しました")
