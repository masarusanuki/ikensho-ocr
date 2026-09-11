# -*- coding: utf-8 -*-
"""テキスト欄の OCR。エンジンは差し替え可能。

方針: 本アプリの読み取りの大半はチェックボックス判定（OCR不要・高精度）で行い、
OCR は氏名・病名・日付などのテキスト欄に限定して使う。
どのエンジンも無い環境では空欄を返し、確認画面で人が入力する運用にできる。
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import unicodedata
from dataclasses import dataclass
from typing import Dict, List, Optional

import cv2
import numpy as np

from .charsets import filter_text

# 日本語の文字（tesseract は文字ごとに空白を入れるので、その除去に使う）
_CJK = re.compile(r"[\u3000-\u30ff\u3400-\u9fff\uf900-\ufaff\uff66-\uff9f]")


def join_japanese(text: str) -> str:
    """日本語の文字と文字の間に入った空白を詰める。

    tesseract の日本語モデルは「石 井 と め」のように1文字ずつ切って返すため、
    そのままでは辞書照合にかからない。英数字の間の空白は意味があるので残す。
    """
    if not text:
        return text
    out = []
    for i, ch in enumerate(text):
        if ch == " " and 0 < i < len(text) - 1 \
                and _CJK.match(text[i - 1]) and _CJK.match(text[i + 1]):
            continue
        out.append(ch)
    return "".join(out)


@dataclass
class OcrResult:
    text: str
    confidence: float      # 0..1
    engine: str


class OcrEngine:
    name = "none"
    available = False

    def read(self, image: np.ndarray, multiline: bool = False,
             charset: str = "") -> OcrResult:
        return OcrResult("", 0.0, self.name)


@dataclass
class Token:
    """読み取った文字の並びと、その横位置（切り抜き画像内の画素）。"""
    text: str
    x0: float
    x1: float
    confidence: float


class NullOcr(OcrEngine):
    """OCR エンジンが無い環境用。常に空欄を返す。"""
    name = "none"
    available = True


def _tokens_default(self, image, charset=""):
    return []


OcrEngine.read_tokens = _tokens_default


class TesseractOcr(OcrEngine):
    """tesseract コマンドを使う（日本語データ jpn が必要）。"""
    name = "tesseract"

    def __init__(self, lang: str = "jpn"):
        self.lang = lang
        self.bin = shutil.which("tesseract")
        self.available = self.bin is not None
        if self.available:
            try:
                langs = subprocess.run([self.bin, "--list-langs"], capture_output=True,
                                       text=True, timeout=20).stdout
                self.available = lang in langs
            except Exception:
                self.available = False

    def _run(self, image: np.ndarray, psm: int) -> tuple:
        """指定の PSM で読み、(本文, 確信度) を返す。

        TSV の block/par/line 番号で行を復元する。単語ごとに改行してしまうと
        複数行の欄が1文字1行になってしまうため。
        """
        with tempfile.TemporaryDirectory() as td:
            src = os.path.join(td, "in.png")
            cv2.imwrite(src, image)
            # 文字種の制限は LSTM では悪影響が出るため、後段のフィルタで行う
            cmd = [self.bin, src, os.path.join(td, "out"), "-l", self.lang,
                   "--psm", str(psm), "-c", "preserve_interword_spaces=1", "tsv"]
            try:
                subprocess.run(cmd, capture_output=True, timeout=60, check=True)
            except Exception:
                return "", 0.0
            tsv = os.path.join(td, "out.tsv")
            if not os.path.exists(tsv):
                return "", 0.0
            lines, confs = {}, []
            with open(tsv, encoding="utf-8", errors="ignore") as fp:
                next(fp, None)
                for row in fp:
                    parts = row.rstrip("\n").split("\t")
                    if len(parts) < 12 or not parts[11].strip():
                        continue
                    lines.setdefault((parts[2], parts[3], parts[4]), []).append(parts[11])
                    try:
                        c = float(parts[10])
                        if c >= 0:
                            confs.append(c / 100.0)
                    except ValueError:
                        pass
        text = "\n".join(" ".join(v) for _, v in sorted(lines.items()))
        conf = round(sum(confs) / len(confs), 3) if confs else 0.0
        return join_japanese(text).strip(), conf

    def read_tokens(self, image: np.ndarray, charset: str = "") -> List[Token]:
        """位置つきで読み取る。日付欄を年・月・日に振り分けるのに使う。"""
        if not self.available:
            return []
        with tempfile.TemporaryDirectory() as td:
            src = os.path.join(td, "in.png")
            cv2.imwrite(src, image)
            cmd = [self.bin, src, os.path.join(td, "out"), "-l", self.lang,
                   "--psm", "7", "-c", "preserve_interword_spaces=1", "tsv"]
            try:
                subprocess.run(cmd, capture_output=True, timeout=60, check=True)
            except Exception:
                return []
            tsv = os.path.join(td, "out.tsv")
            if not os.path.exists(tsv):
                return []
            out = []
            with open(tsv, encoding="utf-8", errors="ignore") as fp:
                next(fp, None)
                for row in fp:
                    c = row.rstrip("\n").split("\t")
                    if len(c) < 12 or not c[11].strip():
                        continue
                    try:
                        left, width, conf = float(c[6]), float(c[8]), float(c[10])
                    except ValueError:
                        continue
                    out.append(Token(c[11], left, left + width,
                                     max(conf, 0.0) / 100.0))
        return out

    def read(self, image: np.ndarray, multiline: bool = False,
             charset: str = "") -> OcrResult:
        if not self.available:
            return OcrResult("", 0.0, self.name)
        # 欄の形によって適した PSM が違うので両方試し、確信度の高い方を採る
        psms = (6, 4) if multiline else (7, 6)
        best_text, best_conf = "", 0.0
        for psm in psms:
            text, conf = self._run(image, psm)
            if not text:
                continue
            if conf > best_conf or (not best_text and text):
                best_text, best_conf = text, conf
        if not multiline:
            best_text = " ".join(best_text.split())
        return OcrResult(filter_text(best_text, charset), best_conf, self.name)


# 日本語の認識モデルの置き場所（tools/fetch_ocr_model.py が入れる）
OCR_MODEL_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "models", "ocr")
# 良いと分かっている順（実測。bench/ocr_truth.json ／ docs/DEVELOPER.md）。
#   japan_v4       文字正解率 78.0% / 0.7秒/欄 … 速さと精度の釣り合いが最も良い
#   ppocrv5_mobile         66.4% / 0.8秒
#   japan_v3               71.9% / 0.7秒
#   ppocrv5_server         78.0% / 9.7秒 … 完全一致は最も高いが遅すぎるので既定にしない
MODEL_PREFERENCE = ("japan_v4", "ppocrv5_mobile", "japan_v3", "ppocrv5_server")


def installed_ocr_models() -> List[dict]:
    """入っている日本語の認識モデルを、良いと分かっている順に返す。"""
    out = []
    if not os.path.isdir(OCR_MODEL_DIR):
        return out
    for key in os.listdir(OCR_MODEL_DIR):
        conf = os.path.join(OCR_MODEL_DIR, key, "model.json")
        if not os.path.exists(conf):
            continue
        try:
            with open(conf, encoding="utf-8") as fh:
                meta = json.load(fh)
        except Exception:
            continue
        base = os.path.join(OCR_MODEL_DIR, key)
        rec = os.path.join(base, meta.get("rec", ""))
        keys = os.path.join(base, meta.get("keys", ""))
        if not (os.path.exists(rec) and os.path.exists(keys)):
            continue
        det = os.path.join(base, meta.get("det", "")) if meta.get("det") else ""
        out.append(dict(key=key, note=meta.get("note", ""), rec=rec, keys=keys,
                        det=det if det and os.path.exists(det) else ""))
    order = {k: i for i, k in enumerate(MODEL_PREFERENCE)}
    out.sort(key=lambda m: order.get(m["key"], 99))
    return out


class RapidOcr(OcrEngine):
    """rapidocr-onnxruntime（pip のみで導入でき、システム依存が無い）。

    既定の認識モデルは**中国語向け**で、日本語のかな・字体に弱い。
    `models/ocr/` に日本語の認識モデルがあれば、それに差し替えて使う
    （`tools/fetch_ocr_model.py` で取得。実測は docs/DEVELOPER.md）。
    """
    name = "rapidocr"

    def __init__(self, model: Optional[str] = None):
        self.engine = None
        self.model = None
        try:
            from rapidocr_onnxruntime import RapidOCR
        except Exception:
            self.available = False
            return
        # model 未指定なら、入っている中でいちばん良いものを使う。
        # "default" と指定した場合は、rapidocr 同梱の（中国語向け）モデルを使う。
        found = [] if model == "default" else installed_ocr_models()
        if model and model != "default":
            found = [m for m in found if m["key"] == model]
        try:
            if found:
                m = found[0]
                kwargs = dict(rec_model_path=m["rec"], rec_keys_path=m["keys"])
                if m["det"]:
                    kwargs["det_model_path"] = m["det"]
                self.engine = RapidOCR(**kwargs)
                self.model = m["key"]
                self.name = f"rapidocr:{m['key']}"
            elif model and model != "default":
                self.available = False        # 指定されたモデルが無い
                return
            else:
                self.engine = RapidOCR()      # 既定（中国語向け）
            self.available = True
        except Exception:
            self.available = False

    def read_tokens(self, image: np.ndarray, charset: str = "") -> List[Token]:
        """位置つきで読み取る。日付欄を年・月・日に振り分けるのに使う。"""
        if not self.available:
            return []
        try:
            res, _ = self._run(cv2.cvtColor(image, cv2.COLOR_GRAY2BGR))
        except Exception:
            return []
        out = []
        for r in (res or []):
            xs = [float(p[0]) for p in r[0]]
            out.append(Token(r[1], min(xs), max(xs),
                             float(r[2]) if len(r) > 2 else 0.5))
        return out

    # 検出した文字が少なすぎるとき、全体1行の読みを採るための条件。
    # 「はしもと さぶろう」が「しも」になる（検出が一部しか拾えない）ので、
    # 文字数が明らかに多い方を採る。確信度が低いものは採らない。
    WHOLE_MIN_CONF = 0.50
    WHOLE_MIN_GAIN = 3       # これだけ文字数が増えるなら乗り換える

    def _read_whole(self, bgr: np.ndarray):
        """切り抜き全体を1行として読む（位置の検出を通さない）。"""
        try:
            flat, _ = self.engine(bgr, use_det=False, use_rec=True)
        except Exception:
            return None
        if not flat:
            return None
        h, w = bgr.shape[:2]
        box = [[0.0, 0.0], [float(w), 0.0], [float(w), float(h)], [0.0, float(h)]]
        return [[box, r[0], r[1]] for r in flat]

    def _run(self, bgr: np.ndarray, single_line: bool = False):
        """文字の位置を見つけてから読む。見つからなければ全体を1行として読む。

        欄の切り抜きは「横に長く縦が短い帯」なので、位置の検出が
        まるごと失敗することがある。**実測で、検出が空だった欄を
        全体1行として読ませると読めた**（ふりがな欄で顕著）。

            いしかわ みつこ  → 検出あり: 何も返らない
                             → 全体1行: 「いしかわみつと」

        ブラウザ版には元から同じ受けがあり、Python 版だけ無かった。
        """
        res, _ = self.engine(bgr)
        if not res:
            return self._read_whole(bgr), True
        if not single_line:
            return res, False
        # 1行の欄では、検出が一部しか拾えていないことがある。
        # 全体1行の読みと比べ、明らかに文字数が多ければそちらを採る。
        whole = self._read_whole(bgr)
        if not whole:
            return res, False
        got = sum(len(str(r[1])) for r in res)
        alt = sum(len(str(r[1])) for r in whole)
        conf = min(float(r[2]) for r in whole)
        if alt >= got + self.WHOLE_MIN_GAIN and conf >= self.WHOLE_MIN_CONF:
            return whole, True
        return res, False

    def read(self, image: np.ndarray, multiline: bool = False,
             charset: str = "") -> OcrResult:
        if not self.available:
            return OcrResult("", 0.0, self.name)
        try:
            res, whole = self._run(cv2.cvtColor(image, cv2.COLOR_GRAY2BGR),
                                   single_line=not multiline)
        except Exception:
            return OcrResult("", 0.0, self.name)
        if not res:
            return OcrResult("", 0.0, self.name)
        # RapidOCR は検出した順に返すため、そのままだと語順が入れ替わる。
        # 実測で「4 年 1 月 24 日」が「年1 月24 4 日」になった。
        # 位置（上から下、左から右）に並べ直す。
        items = []
        for r in res:
            xs = [float(p[0]) for p in r[0]]
            ys = [float(p[1]) for p in r[0]]
            items.append(dict(top=min(ys), left=min(xs), height=max(ys) - min(ys),
                              text=r[1], conf=float(r[2]) if len(r) > 2 else 0.5))
        if items:
            heights = sorted(i["height"] for i in items)
            med = heights[len(heights) // 2] or 1.0
            spread = max(i["top"] for i in items) - min(i["top"] for i in items)
            if spread < med * 0.6:
                # 1行の切り抜き。行を分けると語順が壊れるので横位置だけで並べる
                items.sort(key=lambda i: i["left"])
            else:
                items.sort(key=lambda i: (round(i["top"] / (med * 0.7)), i["left"]))
        lines = [i["text"] for i in items]
        confs = [i["conf"] for i in items]
        text = join_japanese(("\n" if multiline else " ").join(lines).strip())
        conf = round(sum(confs) / len(confs), 3) if confs else 0.5
        return OcrResult(filter_text(text, charset), conf, self.name)


class MangaOcr(OcrEngine):
    """manga-ocr（日本語特化・CPU動作）。

    手書きの日本語を tesseract より読めることがある一方、
    **文字が少ない画像では、もっともらしい文章を作り出す**（生成型モデルのため）。
    実測で「牛久愛和総合病院」の欄から「ここで、年の経験経営者には」を出力した。
    そのため既定では使わず、明示的に選んだ場合のみ、
    しかも「候補の1つ」として扱う。
    """
    name = "mangaocr"

    def __init__(self):
        self.model = None
        try:
            from manga_ocr import MangaOcr as _M
            self.model = _M()
            self.available = True
        except Exception:
            self.available = False

    @staticmethod
    def _tighten(gray: np.ndarray) -> np.ndarray:
        """罫線を除き、文字のある範囲に切り詰める（余白が広いと創作しやすい）。"""
        g = cv2.fastNlMeansDenoising(gray, None, 5, 7, 21)
        bw = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
        h, w = bw.shape
        hk = cv2.getStructuringElement(cv2.MORPH_RECT, (max(20, int(w * 0.45)), 1))
        vk = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(20, int(h * 0.6))))
        rules = cv2.dilate(cv2.bitwise_or(cv2.morphologyEx(bw, cv2.MORPH_OPEN, hk),
                                          cv2.morphologyEx(bw, cv2.MORPH_OPEN, vk)),
                           np.ones((3, 3), np.uint8))
        ink = cv2.morphologyEx(cv2.bitwise_and(bw, cv2.bitwise_not(rules)),
                               cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
        ys, xs = np.where(ink > 0)
        if len(xs) < 15:
            return gray
        pad = 8
        x0, x1 = max(0, xs.min() - pad), min(w, xs.max() + pad)
        y0, y1 = max(0, ys.min() - pad), min(h, ys.max() + pad)
        if x1 - x0 < 8 or y1 - y0 < 8:
            return gray
        return gray[y0:y1, x0:x1]

    def read(self, image: np.ndarray, multiline: bool = False,
             charset: str = "") -> OcrResult:
        if not self.available:
            return OcrResult("", 0.0, self.name)
        try:
            from PIL import Image
            text = self.model(Image.fromarray(self._tighten(image)))
        except Exception:
            return OcrResult("", 0.0, self.name)
        text = join_japanese((text or "").strip())
        # 確信度を返さないモデルなので、控えめな固定値にする
        return OcrResult(filter_text(text, charset), 0.45 if text else 0.0, self.name)


class EnsembleOcr(OcrEngine):
    """複数のエンジンで読み、良い方を採る。

    実測では tesseract は印刷された漢字と複数行の文章に強く、
    RapidOCR は短い欄と数字に強い、というように得意分野が違う。
    どちらを採るかは、確信度だけでなく医療辞書との一致度も見て決める
    （判定は呼び出し側の pick_best に任せる）。
    """
    name = "ensemble"

    def __init__(self, engines: List[OcrEngine]):
        self.engines = [e for e in engines if e.available]
        self.available = bool(self.engines)
        self.name = "+".join(e.name for e in self.engines) or "none"

    def read_all(self, image: np.ndarray, multiline: bool = False,
                 charset: str = "") -> List[OcrResult]:
        return [e.read(image, multiline, charset) for e in self.engines]

    def read(self, image: np.ndarray, multiline: bool = False,
             charset: str = "") -> OcrResult:
        results = self.read_all(image, multiline, charset)
        results = [r for r in results if r.text] or results
        if not results:
            return OcrResult("", 0.0, self.name)
        return max(results, key=lambda r: r.confidence)


_ENGINES = {"tesseract": TesseractOcr, "rapidocr": RapidOcr,
            "mangaocr": MangaOcr, "none": NullOcr}


def _make(name: str) -> OcrEngine:
    """`rapidocr:ppocrv5_mobile` のようなモデル指定も受ける。"""
    if name.startswith("rapidocr:"):
        return RapidOcr(name.split(":", 1)[1])
    if name == "vlm" or name.startswith("vlm:"):
        # VLM は読み込みが重いので使い回す。循環 import を避けてここで読む
        from . import vlm as vlm_mod
        return vlm_mod.get_engine(name.split(":", 1)[1] if ":" in name else None)
    return _ENGINES.get(name, NullOcr)()


def get_engine(name: str = "auto") -> OcrEngine:
    """OCR エンジンを用意する。

      auto            … 使えるものを1つ選ぶ（速い）
      ensemble        … 使えるものを全て使い、良い結果を採る（遅いが精度は上）
      rapidocr        … 日本語モデルが入っていればそれを使う
      rapidocr:<名前>  … 認識モデルを指定する（models/ocr/<名前>）
      vlm / vlm:<名前> … 画像を見て答えるLLMで読む（models/vlm/<名前>）
      名前指定         … tesseract / rapidocr / mangaocr / none

    `auto` では VLM を選ばない。実測で PP-OCR のほうが速く正確なため
    （VLM は読めない画像からもそれらしい文字を作る。`vlm.py` の説明を参照）。
    """
    if name in ("ensemble", "ensemble+manga"):
        keys = ["rapidocr", "tesseract"]
        if name == "ensemble+manga":
            keys.append("mangaocr")
        eng = EnsembleOcr([_make(k) for k in keys])
        return eng if eng.available else NullOcr()
    if name != "auto":
        eng = _make(name)
        return eng if eng.available else NullOcr()
    # 日本語の認識モデルが入っていれば、それがいちばん良い（実測）
    for key in ("rapidocr", "tesseract"):
        eng = _make(key)
        if eng.available:
            if key == "rapidocr" and not eng.model:
                continue          # 中国語向けの既定モデルは後回し
            return eng
    for key in ("tesseract", "rapidocr"):
        eng = _make(key)
        if eng.available:
            return eng
    return NullOcr()


def available_engines() -> List[str]:
    out = [f"rapidocr:{m['key']}" for m in installed_ocr_models()]
    try:
        from . import vlm as vlm_mod
        # 読み込まずに「入っているか」だけを見る（モデルは数GBある）
        if vlm_mod.available():
            out += [f"vlm:{m['key']}" for m in vlm_mod.installed_models()]
    except Exception:
        pass
    for key, cls in _ENGINES.items():
        if key == "mangaocr":
            # モデル読み込みが重いので、導入されているかだけを見る
            try:
                import manga_ocr  # noqa: F401
                out.append(key)
            except Exception:
                pass
            continue
        try:
            if cls().available:
                out.append(key)
        except Exception:
            pass
    return out


class DigitReader:
    """日付欄のように「数字しか入らない欄」を読むための専用処理。

    小さな枠を1つずつ読ませると、1桁の数字は検出に失敗しやすい。
    そこで**欄の全体を一度に読み、読み取れた「年」「月」「日」で区切って**
    数字を振り分ける。区切り文字は様式に印刷されているので必ず写っており、
    小枠の座標を様式ごとに用意しなくても成立する。

    区切り文字が読めなかった場合は、数字の並び順（1つ目=年、2つ目=月、
    3つ目=日）で割り当て、テンプレートに小枠があればそれで補正する。
    """

    MARKS = {"年": "year", "月": "month", "日": "day"}

    def __init__(self):
        self.engines = [e for e in (RapidOcr(), TesseractOcr()) if e.available]
        self.available = bool(self.engines)

    @staticmethod
    def _items(token: "Token"):
        """トークンを1文字ずつ、位置つきに展開する。

        丸数字（④）や全角数字（４）も混ざるので、ここで半角数字に正規化する。
        str.isdigit() は ④ にも True を返すが int() は失敗するため、
        正規化しないと落ちる。
        """
        text = unicodedata.normalize("NFKC", token.text or "")
        n = len(text)
        if n == 0:
            return []
        span = (token.x1 - token.x0) / n
        return [(ch, token.x0 + span * i, token.x0 + span * (i + 1))
                for i, ch in enumerate(text)]

    @staticmethod
    def _is_digit(ch: str) -> bool:
        """半角数字だけを数字として扱う（丸数字などは除く）。"""
        return len(ch) == 1 and "0" <= ch <= "9"

    def _assign(self, chars, slots_px):
        """左から順に見て、数字を年・月・日に振り分ける。"""
        parts = {"year": None, "month": None, "day": None}
        order = ["year", "month", "day"]
        cur, idx = "", 0
        cur_x = None
        used_marks = False

        def commit(key, text, x):
            """数字を割り当てる。桁数が合わないものは捨てる。

            切り詰めると「2024年」が「20年」になり、もっともらしい別の
            日付が出来上がってしまう。読めなかったものとして扱う方が安全。
            """
            if not text or key is None:
                return
            if len(text) > 2 or not all("0" <= c <= "9" for c in text):
                return
            if parts.get(key) is None:
                parts[key] = int(text)

        for ch, cx0, cx1 in chars:
            if self._is_digit(ch):
                if not cur:
                    cur_x = cx0
                cur += ch
                continue
            # 元年は「元」と書かれる。数字ではないので、ここで 1 として扱う
            if ch == "元" and not cur:
                cur, cur_x = "1", cx0
                continue
            if ch in self.MARKS:
                used_marks = True
                commit(self.MARKS[ch], cur, cur_x)
                idx = order.index(self.MARKS[ch]) + 1
                cur, cur_x = "", None
                continue
            if cur:
                # 区切り文字以外で切れた場合は順番で割り当てる
                if not used_marks and idx < len(order):
                    commit(order[idx], cur, cur_x)
                    idx += 1
                elif slots_px:
                    key = self._slot_of(cur_x, slots_px)
                    commit(key, cur, cur_x)
                cur, cur_x = "", None
        if cur:
            if not used_marks and idx < len(order):
                commit(order[idx], cur, cur_x)
            elif slots_px:
                commit(self._slot_of(cur_x, slots_px), cur, cur_x)
            elif idx < len(order):
                commit(order[idx], cur, cur_x)
        return parts

    @staticmethod
    def _slot_of(x, slots_px):
        if x is None or not slots_px:
            return None
        best, bestd = None, None
        for key, (s0, s1) in slots_px.items():
            c = (s0 + s1) / 2
            d = abs(x - c)
            if bestd is None or d < bestd:
                best, bestd = key, d
        return best

    def read_date(self, warped: np.ndarray, rect: List[float],
                  slots: Optional[Dict[str, List[float]]] = None) -> Dict[str, tuple]:
        """日付欄を読み、{"year": (値, 確信度), ...} を返す。"""
        result = {k: (None, 0.0) for k in ("year", "month", "day")}
        if not self.available:
            return result
        pad = 0.02
        roi = prepare_roi(warped, rect, pad=pad, target_height=DATE_TARGET_H)
        if roi is None:
            return result
        H, W = warped.shape
        x, y, w, h = rect
        src_x0 = max(0, int(round((x - w * pad) * W)))
        src_x1 = min(W, int(round((x + w + w * pad) * W)))
        src_w = max(src_x1 - src_x0, 1)
        border = 10
        inner_w = max(roi.shape[1] - border * 2, 1)

        slots_px = None
        if slots:
            slots_px = {k: (v[0] * W, (v[0] + v[2]) * W) for k, v in slots.items()}

        best, best_n, best_conf = None, -1, 0.0
        for eng in self.engines:
            tokens = eng.read_tokens(roi)
            if not tokens:
                continue
            chars = []
            for t in sorted(tokens, key=lambda t: t.x0):
                for ch, cx0, cx1 in self._items(t):
                    px0 = src_x0 + (cx0 - border) / inner_w * src_w
                    px1 = src_x0 + (cx1 - border) / inner_w * src_w
                    chars.append((ch, px0, px1))
            parts = self._assign(chars, slots_px)
            # 月・日の範囲を確かめる
            if parts["month"] is not None and not 1 <= parts["month"] <= 12:
                parts["month"] = None
            if parts["day"] is not None and not 1 <= parts["day"] <= 31:
                parts["day"] = None
            n = sum(1 for v in parts.values() if v is not None)
            conf = sum(t.confidence for t in tokens) / len(tokens)
            if n > best_n or (n == best_n and conf > best_conf):
                best, best_n, best_conf = parts, n, conf
        if best is None:
            return result
        return {k: (best[k], round(best_conf, 3) if best[k] is not None else 0.0)
                for k in result}


_DIGIT_READER = None


def get_digit_reader() -> DigitReader:
    global _DIGIT_READER
    if _DIGIT_READER is None:
        _DIGIT_READER = DigitReader()
    return _DIGIT_READER


# 切り抜きのノイズ取りの強さ。強くすると薄い鉛筆の線まで消える。0 で切る。
# **全部の欄に効くので、変えるときは日付だけでなく文字欄も測ること**
# （`tools/benchmark_dates.py` と `tools/benchmark_seigo.py --text`）。
# 環境変数で試せるようにしてある: IKENSHO_DENOISE=0 など
DENOISE_H = int(os.environ.get("IKENSHO_DENOISE", "7"))
# 日付欄を OCR に渡すときの高さ。小さい数字の検出に効く
DATE_TARGET_H = int(os.environ.get("IKENSHO_DATE_H", "72"))
# 引き伸ばしたあとに輪郭を立てる強さ（0 で切る）。
# **既定は 0（切る）。** 入れてみたが実測で悪化した。
# 100dpi の入力で 年 74.0% → 70.2%（月・日は変わらず）。
# にじみを戻すつもりが、粒を立てて誤読を増やしたと見ている。
SHARPEN = float(os.environ.get("IKENSHO_SHARPEN", "0"))
# 低解像度向けの引き伸ばし（Lanczos・輪郭立て・ノイズ取りの弱め）を使うか。
# 効果を測るために、以前の動き（Cubic・常にノイズ取り）に戻せるようにしてある
LOWRES = os.environ.get("IKENSHO_LOWRES", "1") != "0"


def prepare_roi(warped: np.ndarray, rect: List[float], pad: float = 0.0,
                target_height: int = 48) -> np.ndarray:
    """テンプレート座標の矩形から OCR 用の切り抜きを作る。"""
    H, W = warped.shape
    x, y, w, h = rect
    px, py = w * pad, h * pad
    x0 = max(0, int(round((x - px) * W)))
    y0 = max(0, int(round((y - py) * H)))
    x1 = min(W, int(round((x + w + px) * W)))
    y1 = min(H, int(round((y + h + py) * H)))
    if x1 - x0 < 4 or y1 - y0 < 4:
        return np.full((8, 8), 255, np.uint8)
    roi = warped[y0:y1, x0:x1]
    return upscale_for_ocr(roi, target_height)


def upscale_for_ocr(roi: np.ndarray, target_height: int) -> np.ndarray:
    """OCR に渡す切り抜きを、読みやすい大きさに整える。

    **解像度の低い入力への備え。** 人が読める程度に写っていても、
    1文字が10px前後だと認識モデルは読めない。元の高さに応じて
    やることを変える。

      - 大きく引き伸ばすとき（低解像度）は Lanczos を使う。
        Cubic はにじむので、細い線が消える
      - 引き伸ばしたあとに軽く輪郭を立てる（にじみを戻す）
      - ノイズ取りは**引き伸ばし率が高いときは弱める**。
        低解像度では1画素が文字の一部なので、消すと線が切れる
    """
    if roi.size == 0:
        return np.full((8, 8), 255, np.uint8)
    h = max(roi.shape[0], 1)
    scale = max(1.0, float(target_height) / h)
    big = LOWRES and scale >= 2.0
    if scale > 1.0:
        # 2倍を超える引き伸ばしは Lanczos（細い線を残す）
        interp = cv2.INTER_LANCZOS4 if big else cv2.INTER_CUBIC
        roi = cv2.resize(roi, None, fx=scale, fy=scale, interpolation=interp)
        if big and SHARPEN > 0:
            # にじみを戻す。強くかけると粒が立つので控えめに
            blur = cv2.GaussianBlur(roi, (0, 0), 1.0)
            roi = cv2.addWeighted(roi, 1.0 + SHARPEN, blur, -SHARPEN, 0)
    # 引き伸ばしが大きいほどノイズ取りを弱める
    strength = DENOISE_H
    if big:
        strength = DENOISE_H // 2 if scale < 3.0 else 0
    if strength > 0:
        roi = cv2.fastNlMeansDenoising(roi, None, strength, 7, 21)
    return cv2.copyMakeBorder(roi, 10, 10, 10, 10, cv2.BORDER_CONSTANT, value=255)


def has_ink(warped: np.ndarray, rect: List[float], threshold: float = 0.008) -> bool:
    """欄に何か書かれているか（空欄なら OCR を省ける）。"""
    H, W = warped.shape
    x, y, w, h = rect
    x0, y0 = max(0, int(x * W)), max(0, int(y * H))
    x1, y1 = min(W, int((x + w) * W)), min(H, int((y + h) * H))
    if x1 - x0 < 4 or y1 - y0 < 4:
        return False
    roi = warped[y0:y1, x0:x1]
    bw = cv2.adaptiveThreshold(roi, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                               cv2.THRESH_BINARY_INV, 31, 12)
    return float((bw > 0).mean()) > threshold
