# -*- coding: utf-8 -*-
"""テキスト欄の OCR。エンジンは差し替え可能。

方針: 本アプリの読み取りの大半はチェックボックス判定（OCR不要・高精度）で行い、
OCR は氏名・病名・日付などのテキスト欄に限定して使う。
どのエンジンも無い環境では空欄を返し、確認画面で人が入力する運用にできる。
"""
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from typing import List, Optional

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


class NullOcr(OcrEngine):
    """OCR エンジンが無い環境用。常に空欄を返す。"""
    name = "none"
    available = True


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


class RapidOcr(OcrEngine):
    """rapidocr-onnxruntime（pip のみで導入でき、システム依存が無い）。"""
    name = "rapidocr"

    def __init__(self):
        self.engine = None
        try:
            from rapidocr_onnxruntime import RapidOCR
            self.engine = RapidOCR()
            self.available = True
        except Exception:
            self.available = False

    def read(self, image: np.ndarray, multiline: bool = False,
             charset: str = "") -> OcrResult:
        if not self.available:
            return OcrResult("", 0.0, self.name)
        try:
            res, _ = self.engine(cv2.cvtColor(image, cv2.COLOR_GRAY2BGR))
        except Exception:
            return OcrResult("", 0.0, self.name)
        if not res:
            return OcrResult("", 0.0, self.name)
        lines = [r[1] for r in res]
        confs = [float(r[2]) for r in res if len(r) > 2]
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


def get_engine(name: str = "auto") -> OcrEngine:
    """OCR エンジンを用意する。

      auto     … 使えるものを1つ選ぶ（速い）
      ensemble … 使えるものを全て使い、良い結果を採る（遅いが精度は上）
      名前指定  … tesseract / rapidocr / none
    """
    if name in ("ensemble", "ensemble+manga"):
        keys = ["tesseract", "rapidocr"]
        if name == "ensemble+manga":
            keys.append("mangaocr")
        eng = EnsembleOcr([_ENGINES[k]() for k in keys])
        return eng if eng.available else NullOcr()
    if name != "auto":
        cls = _ENGINES.get(name, NullOcr)
        eng = cls()
        return eng if eng.available else NullOcr()
    for key in ("tesseract", "rapidocr"):
        eng = _ENGINES[key]()
        if eng.available:
            return eng
    return NullOcr()


def available_engines() -> List[str]:
    out = []
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


def prepare_roi(warped: np.ndarray, rect: List[float], pad: float = 0.0) -> np.ndarray:
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
    # 小さい欄は拡大した方が OCR の精度が上がる
    scale = max(1.0, 48.0 / max(roi.shape[0], 1))
    if scale > 1.0:
        roi = cv2.resize(roi, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    roi = cv2.fastNlMeansDenoising(roi, None, 7, 7, 21)
    roi = cv2.copyMakeBorder(roi, 10, 10, 10, 10, cv2.BORDER_CONSTANT, value=255)
    return roi


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
