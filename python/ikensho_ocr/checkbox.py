# -*- coding: utf-8 -*-
"""チェックボックスの記入判定。

印刷された枠線を除いた「内部のインク量」でチェックの有無を判定する。
OCR を使わないため、手書き・印刷・スキャンいずれでも安定して読める。
"""
from dataclasses import dataclass
from typing import Dict, List

import cv2
import numpy as np

# 内部インク率の判定しきい値
EMPTY_MAX = 0.10     # これ未満なら未チェック
FILLED_MIN = 0.28    # これ以上ならチェック済み


@dataclass
class BoxReading:
    field: str
    opt: int
    fill: float           # 内部インク率 0..1
    checked: bool
    confidence: float     # 0..1
    rect: List[float]


def _binarize(gray: np.ndarray) -> np.ndarray:
    return cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                                 cv2.THRESH_BINARY_INV, 31, 12)


def _fill_ratio(bw: np.ndarray, x: int, y: int, w: int, h: int) -> float:
    """枠線を除いた内部のインク率。枠と重なるチェックも拾えるよう
    枠のすぐ内側から測る。"""
    t = max(1, int(round(min(w, h) * 0.26)))
    if w - 2 * t <= 1 or h - 2 * t <= 1:
        t = max(1, min(w, h) // 4)
    inner = bw[y + t:y + h - t, x + t:x + w - t]
    if inner.size == 0:
        return 0.0
    return float((inner > 0).mean())


def _confidence(fill: float) -> float:
    """しきい値からの距離を 0..1 の確信度に変換する。"""
    if fill <= EMPTY_MAX:
        return round(min(1.0, 0.55 + (EMPTY_MAX - fill) / EMPTY_MAX * 0.45), 3)
    if fill >= FILLED_MIN:
        return round(min(1.0, 0.55 + (fill - FILLED_MIN) / 0.35 * 0.45), 3)
    # グレーゾーン: 中央に近いほど確信度が低い
    mid = (EMPTY_MAX + FILLED_MIN) / 2
    span = (FILLED_MIN - EMPTY_MAX) / 2
    return round(0.15 + abs(fill - mid) / span * 0.35, 3)


def read_boxes(warped: np.ndarray, boxes: List[dict]) -> List[BoxReading]:
    """テンプレート座標系に合わせた画像から全チェックボックスを読み取る。"""
    bw = _binarize(warped)
    H, W = warped.shape
    out = []
    for b in boxes:
        rx, ry, rw, rh = b["rect"]
        x, y = int(round(rx * W)), int(round(ry * H))
        w, h = max(3, int(round(rw * W))), max(3, int(round(rh * H)))
        x = max(0, min(x, W - w))
        y = max(0, min(y, H - h))
        fill = _fill_ratio(bw, x, y, w, h)
        out.append(BoxReading(field=b["field"], opt=b["opt"], fill=round(fill, 4),
                              checked=fill >= (EMPTY_MAX + FILLED_MIN) / 2,
                              confidence=_confidence(fill), rect=b["rect"]))
    return out


def resolve_groups(readings: List[BoxReading], schema) -> Dict[str, dict]:
    """項目ごとにチェック結果をまとめ、単一選択では競合を解消する。

    単一選択(choice)は最も濃い1つを採用し、2位との差が小さいときは
    確信度を下げて「要確認」として扱えるようにする。
    """
    grouped: Dict[str, List[BoxReading]] = {}
    for r in readings:
        grouped.setdefault(r.field, []).append(r)

    result: Dict[str, dict] = {}
    for fid, rs in grouped.items():
        rs.sort(key=lambda r: r.opt)
        f = schema.get(fid)
        if f is None:
            continue

        if f.type == "flag":
            r = rs[0]
            result[fid] = dict(value=r.checked, confidence=r.confidence,
                               detail=[dict(opt=r.opt, fill=r.fill, checked=r.checked)])
            continue

        options = f.options or []
        if f.type == "choice":
            ranked = sorted(rs, key=lambda r: -r.fill)
            top = ranked[0]
            second_fill = ranked[1].fill if len(ranked) > 1 else 0.0
            if top.fill < (EMPTY_MAX + FILLED_MIN) / 2:
                value, conf = None, _confidence(top.fill)
            else:
                value = options[top.opt] if top.opt < len(options) else str(top.opt)
                margin = top.fill - second_fill
                # 2位と差がないほど「どちらか判らない」＝確信度を落とす
                conf = min(top.confidence, round(min(1.0, 0.35 + margin / 0.25 * 0.65), 3))
            result[fid] = dict(value=value, confidence=conf,
                               detail=[dict(opt=r.opt, fill=r.fill, checked=r.checked)
                                       for r in rs])
            continue

        # multi: 各選択肢を独立に判定
        picked = [options[r.opt] if r.opt < len(options) else str(r.opt)
                  for r in rs if r.checked]
        conf = round(min((r.confidence for r in rs), default=0.0), 3)
        result[fid] = dict(value=picked, confidence=conf,
                           detail=[dict(opt=r.opt, fill=r.fill, checked=r.checked)
                                   for r in rs])
    return result
