# -*- coding: utf-8 -*-
"""テキスト欄の OCR。エンジンは差し替え可能。

方針: 本アプリの読み取りの大半はチェックボックス判定（OCR不要・高精度）で行い、
OCR は氏名・病名・日付などのテキスト欄に限定して使う。
どのエンジンも無い環境では空欄を返し、確認画面で人が入力する運用にできる。
"""
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from typing import List, Optional

import cv2
import numpy as np


@dataclass
class OcrResult:
    text: str
    confidence: float      # 0..1
    engine: str


class OcrEngine:
    name = "none"
    available = False

    def read(self, image: np.ndarray, multiline: bool = False) -> OcrResult:
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

    def read(self, image: np.ndarray, multiline: bool = False) -> OcrResult:
        if not self.available:
            return OcrResult("", 0.0, self.name)
        psm = "6" if multiline else "7"
        with tempfile.TemporaryDirectory() as td:
            src = os.path.join(td, "in.png")
            cv2.imwrite(src, image)
            cmd = [self.bin, src, os.path.join(td, "out"), "-l", self.lang,
                   "--psm", psm, "-c", "preserve_interword_spaces=1", "tsv"]
            try:
                subprocess.run(cmd, capture_output=True, timeout=60, check=True)
            except Exception:
                return OcrResult("", 0.0, self.name)
            tsv = os.path.join(td, "out.tsv")
            if not os.path.exists(tsv):
                return OcrResult("", 0.0, self.name)
            words, confs = [], []
            with open(tsv, encoding="utf-8", errors="ignore") as fp:
                next(fp, None)
                for line in fp:
                    parts = line.rstrip("\n").split("\t")
                    if len(parts) < 12:
                        continue
                    text, conf = parts[11], parts[10]
                    if not text.strip():
                        continue
                    words.append(text)
                    try:
                        c = float(conf)
                        if c >= 0:
                            confs.append(c / 100.0)
                    except ValueError:
                        pass
        text = ("\n" if multiline else " ").join(words).strip()
        conf = round(sum(confs) / len(confs), 3) if confs else 0.0
        return OcrResult(text, conf, self.name)


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

    def read(self, image: np.ndarray, multiline: bool = False) -> OcrResult:
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
        text = ("\n" if multiline else " ").join(lines).strip()
        conf = round(sum(confs) / len(confs), 3) if confs else 0.5
        return OcrResult(text, conf, self.name)


_ENGINES = {"tesseract": TesseractOcr, "rapidocr": RapidOcr, "none": NullOcr}


def get_engine(name: str = "auto") -> OcrEngine:
    """利用可能な OCR エンジンを返す。auto なら精度の高い順に探す。"""
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
