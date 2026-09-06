# -*- coding: utf-8 -*-
"""テキスト欄の切り出しを整える。

測ったテキスト欄の左端が記入の先頭に食い込んでいると、
「対処方針」のような記述欄で最初の1〜2文字が落ちる。
かといって一律に左へ広げると、印刷されたラベル（「→ 対処方針 （」など）まで
読み込んでしまう。

そこで**白紙様式**を見て、左どなりの印刷内容にぶつからない範囲でだけ広げる。
白紙様式は様式ごとに用意してあり、チェック欄の差分にも使っているもの。
"""
from typing import List, Optional

import cv2
import numpy as np

# 左へ広げてよい上限（ページ幅に対する割合）
MAX_PAD = 0.030
# 印刷内容との間に空ける余白。行の高さに対する割合（文字の隙間ぶん）
GAP_RATIO = 0.35
GAP_MIN = 3
# その列に印刷内容があるとみなす画素数
INK_MIN = 2


def _printed(blank: np.ndarray) -> np.ndarray:
    bw = cv2.adaptiveThreshold(blank, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                               cv2.THRESH_BINARY_INV, 31, 12)
    # 罫線の1画素の途切れやにじみで判定がぶれないよう、少し太らせる
    return cv2.dilate(bw, np.ones((3, 3), np.uint8), iterations=1)


def widen_left(blank: Optional[np.ndarray], rect: List[float],
               max_pad: float = MAX_PAD) -> List[float]:
    """印刷内容にぶつからない範囲で、欄の左端を左へ広げた矩形を返す。

    白紙様式が無い場合や、すぐ左に印刷内容がある場合は元の矩形のまま返す。
    """
    if blank is None or blank.size == 0:
        return rect
    H, W = blank.shape[:2]
    x, y, w, h = rect
    x0 = int(round(x * W))
    y0, y1 = max(0, int(round(y * H))), min(H, int(round((y + h) * H)))
    if x0 <= 1 or y1 - y0 < 4:
        return rect

    gap = max(GAP_MIN, int(round((y1 - y0) * GAP_RATIO)))
    # 欄の左端のすぐ内側に印刷（「（」など）がある場合は、
    # もともと印刷の際まで測れているので広げない
    inside = _printed(blank[y0:y1, x0:min(W, x0 + gap)])
    if inside.size and ((inside > 0).sum(axis=0) >= INK_MIN).any():
        return rect

    limit = max(0, x0 - int(round(max_pad * W)))
    band = _printed(blank[y0:y1, limit:x0])
    if band.size == 0:
        return rect
    col = (band > 0).sum(axis=0)

    # 欄の左端から左へ、印刷内容にぶつかるまで戻る
    new_x0 = x0
    for i in range(len(col) - 1, -1, -1):
        if col[i] >= INK_MIN:
            break
        new_x0 = limit + i
    new_x0 = min(x0, new_x0 + gap)
    if new_x0 >= x0:
        return rect
    nx = new_x0 / W
    return [nx, y, w + (x - nx), h]
