# -*- coding: utf-8 -*-
"""VLM（画像を見て答えるLLM）で欄の文字を読む。任意機能・切り替え式。

**既定ではない。** PP-OCR による読み取り（`ocr.py`）のほうが速く、
測った精度も高い。VLM を入れたのは次の2つの目的のため。

  1. 手書きの崩れた字など、文字認識モデルが苦手な欄を別の方法で読めるようにする
  2. どちらが良いかを**同じ正解データで比べられる**ようにする
     （`tools/benchmark_ocr.py --engine vlm`）

危ないところ: VLM は**読めない画像からもそれらしい文字を作る**。
`llm.py` に書いた「候補を出すだけ」の原則と同じ理由で、
ここでも次の歯止めをかけている。

  - 「読めない場合は空で返す」と明示して聞く
  - 説明・前置き・引用符を機械的に落とす（モデルは付けたがる）
  - 欄の文字種（`charset`）で後から絞る。呼び出し側の既存の検算も通る
  - 確信度を 0.55 で頭打ちにする。**自動確定させない**

モデルは GGUF（llama.cpp）で動かす。取得は `tools/fetch_vlm_model.py`。
"""
import atexit
import contextlib
import os
import re
import threading
from typing import List, Optional

import cv2
import numpy as np

from .charsets import filter_text
from .ocr import OcrEngine, OcrResult, Token, join_japanese

# モデルの置き場。`<リポジトリ>/models/vlm/<名前>/`
DEFAULT_VLM_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "models", "vlm")

SYSTEM_PROMPT = (
    "あなたは日本語の書類を書き写す係です。"
    "画像に写っている文字を、そのまま書き写してください。"
    "説明・前置き・引用符・読みの補足は付けず、書かれている文字だけを出力します。"
    "印刷された罫線・カッコ・単位は書き写しません。"
    "文字が無い、または読み取れない場合は 空 とだけ出力します。"
)
PROMPT = "この欄に書かれている文字を、そのまま書き写してください。"
MULTILINE_PROMPT = (
    "この欄に書かれている文字を、そのまま書き写してください。"
    "複数行ある場合は行ごとに改行してください。"
)

# VLM が付けたがる前置き・引用符を落とす
_PREFIX = re.compile(
    r"^\s*(画像|この欄|答え|回答|書かれている文字|文字)"
    r"[にのはもがで\s]*(の?文字)?[にのはもがで\s]*[:：]?\s*")
_QUOTES = "「」『』\"'“”‘’`"
# 引用符でくくった中身。前置きを付けてきた場合はここだけを採る
_QUOTED = re.compile(r"[「『\"“]([^「」『』\"“”]{1,80})[」』\"”]")
# 「読めません」系の返事は空として扱う
_EMPTY_WORDS = ("空", "空白", "空欄", "なし", "無し", "ありません",
                "読み取れません", "読めません", "判読できません", "不明",
                "文字はありません", "記入なし", "記入はありません")
CONF_CAP = 0.55      # 自動確定させないための上限
TARGET_HEIGHT = 96   # 小さい切り抜きはここまで拡大して渡す
PAD = 12             # 周りに足す白の幅


def _clean(text: str) -> str:
    """前置き・引用符・言い添えを落とす。

    「画像には『脳梗塞後遺症』と書かれています」のように説明文で返してくることが
    ある。引用符でくくられていればその中だけを採る。
    """
    out = []
    for line in (text or "").splitlines():
        line = _PREFIX.sub("", line.strip())
        quoted = _QUOTED.findall(line)
        if quoted:
            # いちばん長い引用をその行の中身とみなす
            line = max(quoted, key=len)
        line = line.strip().strip(_QUOTES).strip()
        if not line or line in _EMPTY_WORDS:
            continue
        out.append(line)
    return "\n".join(out)


def prepare(gray: np.ndarray) -> np.ndarray:
    """小さすぎる切り抜きを拡大し、白で縁取る。"""
    if gray.size == 0:
        return gray
    h = gray.shape[0]
    if h < TARGET_HEIGHT:
        f = min(4.0, TARGET_HEIGHT / max(h, 1))
        gray = cv2.resize(gray, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)
    return cv2.copyMakeBorder(gray, PAD, PAD, PAD, PAD,
                              cv2.BORDER_CONSTANT, value=255)


def installed_models() -> List[dict]:
    """`models/vlm/` に入っている VLM の一覧。"""
    out = []
    if not os.path.isdir(DEFAULT_VLM_DIR):
        return out
    for name in sorted(os.listdir(DEFAULT_VLM_DIR)):
        base = os.path.join(DEFAULT_VLM_DIR, name)
        if not os.path.isdir(base):
            continue
        files = os.listdir(base)
        model = next((f for f in files
                      if f.endswith(".gguf") and "mmproj" not in f.lower()), None)
        mmproj = next((f for f in files
                       if f.endswith(".gguf") and "mmproj" in f.lower()), None)
        if not model or not mmproj:
            continue
        size = sum(os.path.getsize(os.path.join(base, f)) for f in (model, mmproj))
        out.append(dict(key=name, model=os.path.join(base, model),
                        mmproj=os.path.join(base, mmproj),
                        size_mb=round(size / 1048576)))
    return out


def _find_model(key: Optional[str] = None) -> Optional[dict]:
    env = os.environ.get("IKENSHO_VLM_MODEL")
    if env and os.path.isdir(env):
        DEFAULT = os.listdir(env)
        model = next((f for f in DEFAULT
                      if f.endswith(".gguf") and "mmproj" not in f.lower()), None)
        mmproj = next((f for f in DEFAULT
                       if f.endswith(".gguf") and "mmproj" in f.lower()), None)
        if model and mmproj:
            return dict(key=os.path.basename(env.rstrip("/")),
                        model=os.path.join(env, model),
                        mmproj=os.path.join(env, mmproj), size_mb=0)
    models = installed_models()
    if key:
        return next((m for m in models if m["key"] == key), None)
    return models[0] if models else None


# 画像を扱えるチャットハンドラ。モデルの系列ごとに違う
_HANDLERS = (
    ("qwen2.5-vl", "Qwen25VLChatHandler"),
    ("qwen2_5-vl", "Qwen25VLChatHandler"),
    ("qwen2.5vl", "Qwen25VLChatHandler"),
    ("minicpm", "MiniCPMv26ChatHandler"),
    ("moondream", "MoondreamChatHandler"),
    ("gemma", "Gemma4ChatHandler"),
    ("llava-1.6", "Llava16ChatHandler"),
    ("llava", "Llava15ChatHandler"),
)


def _handler_name(key: str) -> str:
    low = key.lower()
    for token, cls in _HANDLERS:
        if token in low:
            return cls
    # 系列が分からない場合は llama.cpp の汎用マルチモーダル経路に任せる
    return "MTMDChatHandler"


# 標準出力の差し替えはプロセス全体に効くので、同時に2つ走らせない
_SILENCE_LOCK = threading.Lock()


@contextlib.contextmanager
def _silence():
    """C 側が標準出力・標準エラーに直接書く分を捨てる。

    llama.cpp の画像符号化の経過（`image slice encoded in ...`）は
    ログの受け口を通らず直接書かれるため、ファイル記述子ごと差し替える。
    失敗は例外で分かるので、捨てても情報は落ちない。

    **プロセス全体のファイル記述子を差し替える**ため、同時に走ると
    復帰が入れ違って標準出力が /dev/null に固定されてしまう。錠をかける。
    """
    with _SILENCE_LOCK:
        yield from _silence_inner()


def _silence_inner():
    try:
        null = os.open(os.devnull, os.O_WRONLY)
        saved = (os.dup(1), os.dup(2))
    except OSError:
        yield
        return
    try:
        os.dup2(null, 1)
        os.dup2(null, 2)
        yield
    finally:
        os.dup2(saved[0], 1)
        os.dup2(saved[1], 2)
        for fd in (null, saved[0], saved[1]):
            try:
                os.close(fd)
            except OSError:
                pass


_LOG_CB = None


def _quiet_llama() -> None:
    """llama.cpp の進捗ログ（画像の符号化の経過など）を止める。

    `verbose=False` では C 側のログが止まらず、1欄ごとに数十行が端末に出る。
    ログの受け口を空の関数に差し替えて黙らせる。
    """
    global _LOG_CB
    if _LOG_CB is not None:
        return
    try:
        import llama_cpp
        @llama_cpp.llama_log_callback
        def _sink(level, text, user_data):   # noqa: ARG001
            pass
        _LOG_CB = _sink                      # GC されると落ちるので持っておく
        llama_cpp.llama_log_set(_LOG_CB, llama_cpp.ctypes.c_void_p(0))
    except Exception:
        _LOG_CB = False


class VlmOcr(OcrEngine):
    """画像を見て文字を書き写す VLM を、OCR エンジンとして使えるようにする。"""

    def __init__(self, model: Optional[str] = None, n_ctx: int = 4096,
                 threads: Optional[int] = None):
        self.available = False
        self.name = "vlm"
        self.model = ""
        self._llm = None
        conf = _find_model(model)
        if conf is None:
            return
        try:
            from llama_cpp import Llama
            from llama_cpp import llama_chat_format as fmt
        except Exception:
            return
        _quiet_llama()
        handler_cls = getattr(fmt, _handler_name(conf["key"]), None)
        if handler_cls is None:
            return
        try:
            with _silence():
                handler = handler_cls(clip_model_path=conf["mmproj"], verbose=False)
                self._llm = Llama(model_path=conf["model"], chat_handler=handler,
                                  n_ctx=n_ctx,
                                  n_threads=threads or (os.cpu_count() or 4),
                                  logits_all=False, verbose=False)
        except Exception:
            self._llm = None
            return
        self.model = conf["key"]
        self.name = f"vlm:{conf['key']}"
        self.available = True
        # 終了時に自分で閉じる。インタプリタ終了に任せると llama.cpp の後始末が
        # 閉じた標準出力に書こうとして、終了間際に例外の山を出す
        atexit.register(self.close)

    def close(self) -> None:
        llm, self._llm = self._llm, None
        self.available = False
        if llm is not None:
            try:
                llm.close()
            except Exception:
                pass

    # ------------------------------------------------------------ 読み取り
    def _ask(self, gray: np.ndarray, prompt: str, max_tokens: int) -> str:
        ok, buf = cv2.imencode(".png", prepare(gray))
        if not ok:
            return ""
        import base64
        url = "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode()
        try:
            with _silence():
                res = self._llm.create_chat_completion(
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": [
                            {"type": "image_url", "image_url": {"url": url}},
                            {"type": "text", "text": prompt},
                        ]},
                    ],
                    max_tokens=max_tokens, temperature=0.0)
            return res["choices"][0]["message"]["content"] or ""
        except Exception:
            return ""

    def read(self, image: np.ndarray, multiline: bool = False,
             charset: str = "") -> OcrResult:
        if not self.available or image is None or image.size == 0:
            return OcrResult("", 0.0, self.name)
        raw = self._ask(image, MULTILINE_PROMPT if multiline else PROMPT,
                        256 if multiline else 64)
        text = _clean(raw)
        if not multiline:
            text = " ".join(text.split())
        text = join_japanese(text)
        text = filter_text(text, charset)
        # 読めた文字数だけを手がかりに確信度を決める。VLM は自己申告しないため。
        conf = 0.0 if not text else min(CONF_CAP, 0.35 + min(len(text), 8) * 0.025)
        return OcrResult(text, round(conf, 3), self.name)

    def read_tokens(self, image: np.ndarray, charset: str = "") -> List[Token]:
        """位置つきの読み取りは持たない（VLM は座標を返さない）。

        日付欄のように位置で振り分ける処理は、呼び出し側で
        テンプレートの小枠を使う経路に落ちる。
        """
        res = self.read(image, charset=charset)
        if not res.text:
            return []
        return [Token(res.text, 0.0, float(image.shape[1]), res.confidence)]


_CACHE: dict = {}


def available() -> bool:
    """VLM を使える環境か（llama.cpp とモデルがそろっているか）。"""
    try:
        import llama_cpp  # noqa: F401
    except Exception:
        return False
    return _find_model() is not None


def get_engine(model: Optional[str] = None) -> OcrEngine:
    """VLM エンジンを用意する（重いので1度だけ読み込んで使い回す）。"""
    key = model or ""
    if key not in _CACHE:
        _CACHE[key] = VlmOcr(model)
    return _CACHE[key]
