# -*- coding: utf-8 -*-
"""国立国会図書館の NDLOCR-Lite で読む。

出どころ: https://github.com/ndl-lab/ndlocr-lite （国立国会図書館 / CC BY 4.0）
取得は `tools/fetch_ndlocr.py`。**CC BY 4.0 なので出典の表示が要る。**

2つの使い方を用意している。

  欄ごと（`NdlOcr`）    … これまでと同じく、欄の切り抜きを1つずつ渡す
  ページ全体（`PageReader`）… ページを1枚まるごと読み、
                             読めた行を欄の位置に振り分ける

**ページ全体の方が速く、手書きに強い。** この認識モデル（PARSeq）は
「1行に切り出した画像」を前提にしており、欄の切り抜きをそのまま渡すと
まるで読めない（実測で『たかはしとめ』が `TOTAL PRON CON...` になる）。
先に検出モデル（DEIM）で行を見つけるのが本来の使い方で、
それをページ単位でやると検出が1回で済む。
"""
import os
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from .charsets import filter_text
from .ocr import OcrEngine, OcrResult, Token, join_japanese

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MODEL_DIR = os.environ.get("IKENSHO_NDLOCR") or os.path.join(ROOT, "models", "ndlocr")

DET_NAME = "deim-s-1024x1024.onnx"
REC_NAME = "parseq-ndl-24x384-50-tiny-300epoch-tegaki3-r8data-202604.onnx"
DET_CLASSES = "ndl.yaml"
REC_CLASSES = "NDLmoji.yaml"

# 行として扱う種類（`ndl.yaml` の名前）。図・表・柱などは読まない
LINE_KINDS = ("line_main", "line_title", "line_caption", "line_note",
              "line_note_tochu", "line_ad")
# 同じ行が二重に検出されることがあるので、重なりがこれ以上なら1つにまとめる
DUP_IOU = 0.55
# 欄に属するとみなす重なり（行の面積のうち、欄に入っている割合）
FIELD_COVER = 0.55


def available() -> bool:
    """モデルがそろっているか。"""
    return all(os.path.exists(os.path.join(MODEL_DIR, n))
               for n in (DET_NAME, REC_NAME, DET_CLASSES, REC_CLASSES))


@dataclass
class Line:
    """読めた1行。座標はページ（テンプレート座標系）の画素。"""
    text: str
    x0: int
    y0: int
    x1: int
    y1: int
    kind: str
    score: float

    @property
    def area(self) -> int:
        return max(0, self.x1 - self.x0) * max(0, self.y1 - self.y0)


def _iou(a: Line, b: Line) -> float:
    ix = max(0, min(a.x1, b.x1) - max(a.x0, b.x0))
    iy = max(0, min(a.y1, b.y1) - max(a.y0, b.y0))
    inter = ix * iy
    union = a.area + b.area - inter
    return inter / union if union else 0.0


class _Models:
    """検出・認識の実体。重いので1組だけ作って使い回す。

    **同時に呼ばない。** onnxruntime の Session 自体は並行して呼べるが、
    ここでは読み込みの重さを避けて1組しか持たないため、
    呼ぶ側（サーバ）で順番に通すこと。
    """

    def __init__(self, model_dir: str = MODEL_DIR):
        self.available = False
        self.det = None
        self.rec = None
        if not available():
            return
        # 取得したラッパ（deim.py / parseq.py）をそのまま使う。
        # 改変しないことで、本家が直ったときに入れ替えるだけで済む
        if model_dir not in sys.path:
            sys.path.insert(0, model_dir)
        try:
            from yaml import safe_load
            from deim import DEIM
            from parseq import PARSEQ
        except Exception:
            return
        try:
            self.det = DEIM(model_path=os.path.join(model_dir, DET_NAME),
                            class_mapping_path=os.path.join(model_dir, DET_CLASSES),
                            score_threshold=0.3, conf_threshold=0.3,
                            iou_threshold=0.4, device="CPU")
            with open(os.path.join(model_dir, REC_CLASSES), encoding="utf-8") as fh:
                chars = list(safe_load(fh)["model"]["charset_train"])
            self.rec = PARSEQ(model_path=os.path.join(model_dir, REC_NAME),
                              charlist=chars, device="CPU")
        except Exception:
            self.det = self.rec = None
            return
        self.available = True

    # -------------------------------------------------------------- 読む
    def lines(self, gray: np.ndarray, min_score: float = 0.35) -> List[Line]:
        """画像から行を見つけて読む。"""
        if not self.available or gray is None or gray.size == 0:
            return []
        bgr = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
        try:
            dets = self.det.detect(bgr)
        except Exception:
            return []
        picked: List[Line] = []
        for d in sorted(dets, key=lambda d: -float(d["confidence"])):
            if d["class_name"] not in LINE_KINDS:
                continue
            if float(d["confidence"]) < min_score:
                continue
            x0, y0, x1, y1 = (int(v) for v in d["box"])
            line = Line("", max(0, x0), max(0, y0), x1, y1,
                        d["class_name"], float(d["confidence"]))
            if line.area < 24:
                continue
            # 同じ行を二重に拾わない（確信度の高い方を残す）
            if any(_iou(line, p) >= DUP_IOU for p in picked):
                continue
            picked.append(line)
        for line in picked:
            crop = bgr[line.y0:line.y1, line.x0:line.x1]
            if crop.size == 0:
                continue
            try:
                line.text = self.rec.read(crop) or ""
            except Exception:
                line.text = ""
        picked = [p for p in picked if p.text.strip()]
        picked.sort(key=lambda p: (p.y0, p.x0))
        return picked


_CACHE: Optional[_Models] = None


def models() -> _Models:
    global _CACHE
    if _CACHE is None:
        _CACHE = _Models()
    return _CACHE


# ------------------------------------------------------------ ページ全体

class PageReader:
    """ページを1枚まるごと読み、行を欄の位置に振り分ける。

    **「文章のように読む」やり方。** 検出が1ページ1回で済むので速く、
    行の前後がつながるぶん認識も安定する。
    """

    def __init__(self, gray: np.ndarray):
        self.height, self.width = gray.shape[:2]
        self.lines = models().lines(gray)

    def __bool__(self) -> bool:
        return bool(self.lines)

    def in_rect(self, rect: List[float], cover: float = FIELD_COVER) -> List[Line]:
        """欄の中に入っている行を、上から順に返す。"""
        x, y, w, h = rect
        rx0, ry0 = x * self.width, y * self.height
        rx1, ry1 = (x + w) * self.width, (y + h) * self.height
        got = []
        for line in self.lines:
            ix = max(0, min(line.x1, rx1) - max(line.x0, rx0))
            iy = max(0, min(line.y1, ry1) - max(line.y0, ry0))
            if line.area and (ix * iy) / line.area >= cover:
                got.append(line)
        got.sort(key=lambda p: (p.y0, p.x0))
        return got

    def text_in(self, rect: List[float], multiline: bool = False,
                charset: str = "", gray: Optional[np.ndarray] = None) -> OcrResult:
        """欄1つぶんの文字列を組み立てる。

        ページ全体の読みでは、**印刷ラベルごと1行として検出される**ことがある。

            検出された行  「■関節の拘縮(部位:両足関節程度:□軽□中■重)」
            欄（部位）    「両足関節」だけ

        欄が行の一部にしかならないので割り当てられない。この場合は
        `gray` を渡してもらって、その欄だけを切り出して読み直す。
        実測では文字欄47個のうち26個がこちらに落ちる。
        """
        got = self.in_rect(rect)
        if not got:
            if gray is not None:
                return self._crop_read(gray, rect, multiline, charset)
            return OcrResult("", 0.0, "ndlocr")
        if multiline:
            text = "\n".join(p.text for p in got)
        else:
            text = " ".join(p.text for p in got)
        text = join_japanese(text)
        conf = round(sum(p.score for p in got) / len(got), 3)
        return OcrResult(filter_text(text, charset), conf, "ndlocr")

    def _crop_read(self, gray: np.ndarray, rect: List[float],
                   multiline: bool, charset: str) -> OcrResult:
        """欄だけを切り出して、その中でもう一度行を見つけて読む。"""
        H, W = gray.shape[:2]
        x, y, w, h = rect
        x0, y0 = max(0, int(round(x * W))), max(0, int(round(y * H)))
        x1, y1 = min(W, int(round((x + w) * W))), min(H, int(round((y + h) * H)))
        if x1 - x0 < 8 or y1 - y0 < 8:
            return OcrResult("", 0.0, "ndlocr")
        lines = models().lines(gray[y0:y1, x0:x1], min_score=0.3)
        if not lines:
            return OcrResult("", 0.0, "ndlocr")
        sep = "\n" if multiline else " "
        text = join_japanese(sep.join(p.text for p in lines))
        conf = round(sum(p.score for p in lines) / len(lines), 3)
        return OcrResult(filter_text(text, charset), conf, "ndlocr")

    def tokens_in(self, rect: List[float]) -> List[Token]:
        """欄の中の行を、横位置つきで返す（日付欄の振り分け用）。"""
        x, w = rect[0], rect[2]
        rx0 = x * self.width
        out = []
        for line in self.in_rect(rect):
            out.append(Token(line.text, float(line.x0 - rx0),
                             float(line.x1 - rx0), line.score))
        return out


# ------------------------------------------------------------ 欄ごと

class NdlOcr(OcrEngine):
    """欄の切り抜きを1つずつ読む使い方（他のエンジンと同じ口）。

    切り抜きの中でもう一度行を見つけてから読む。
    **そのまま認識モデルに渡してはいけない**（1行に切り出した画像が前提のため）。
    """

    name = "ndlocr"

    def __init__(self):
        self._m = models()
        self.available = self._m.available

    def read(self, image: np.ndarray, multiline: bool = False,
             charset: str = "") -> OcrResult:
        if not self.available or image is None or image.size == 0:
            return OcrResult("", 0.0, self.name)
        lines = self._m.lines(image, min_score=0.3)
        if not lines:
            return OcrResult("", 0.0, self.name)
        sep = "\n" if multiline else " "
        text = join_japanese(sep.join(p.text for p in lines))
        conf = round(sum(p.score for p in lines) / len(lines), 3)
        return OcrResult(filter_text(text, charset), conf, self.name)

    def read_tokens(self, image: np.ndarray, charset: str = "") -> List[Token]:
        if not self.available or image is None or image.size == 0:
            return []
        return [Token(p.text, float(p.x0), float(p.x1), p.score)
                for p in self._m.lines(image, min_score=0.3)]
