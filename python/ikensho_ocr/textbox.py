# -*- coding: utf-8 -*-
"""テキスト欄の切り出しを整える。

測ったテキスト欄の左端が記入の先頭に食い込んでいると、
「対処方針」のような記述欄で最初の1〜2文字が落ちる。
かといって一律に左へ広げると、印刷されたラベル（「→ 対処方針 （」など）まで
読み込んでしまう。

そこで**白紙様式**を見て、左どなりの印刷内容にぶつからない範囲でだけ広げる。
白紙様式は様式ごとに用意してあり、チェック欄の差分にも使っているもの。
"""
import math

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


def _r(v: float) -> int:
    """四捨五入。ブラウザの Math.round と同じ規則にする（Python の round は偶数丸め）。"""
    return int(math.floor(v + 0.5))


def _printed(blank: np.ndarray) -> np.ndarray:
    bw = cv2.adaptiveThreshold(blank, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                               cv2.THRESH_BINARY_INV, 31, 12)
    # 罫線の1画素の途切れやにじみで判定がぶれないよう、少し太らせる
    return cv2.dilate(bw, np.ones((3, 3), np.uint8), iterations=1)


# 書き込みの周りに残す余白（文字の高さに対する割合）。
# 詰めすぎると認識モデルが読めなくなる
INK_MARGIN = 0.35


def ink_crop(warped: np.ndarray, blank: Optional[np.ndarray],
             rect: List[float], margin: float = INK_MARGIN) -> List[float]:
    """書き込みのある範囲まで矩形を詰める。

    欄には印刷された罫線・カッコ・単位（cm など）が入っている。
    認識モデルはそれも文字として読もうとするので、**書き込みだけ**に寄せた方が
    正確に読める。白紙様式との差分を見れば、印刷か書き込みかが分かる。

    実測（bench/ocr_truth.json・72項目）:
    文字正解率 78.0% → **84.6%**、完全一致 40.0% → **60.0%**（japan_v4）。

    差分が取れない・書き込みが見当たらない場合は、元の矩形をそのまま返す。
    """
    if blank is None or blank.size == 0:
        return rect
    from . import text_check
    # 文字欄の差分は枠の判定より弱く白紙を太らせる（text_check を参照）
    diff = text_check.mark_layer(warped, blank)
    if diff is None:
        return rect
    H, W = diff.shape[:2]
    x, y, w, h = rect
    if not all(np.isfinite(v) for v in (x, y, w, h)):
        return rect
    x0, y0 = max(0, _r(x * W)), max(0, _r(y * H))
    x1, y1 = min(W, _r((x + w) * W)), min(H, _r((y + h) * H))
    if x1 - x0 < 8 or y1 - y0 < 8:
        return rect
    win = diff[y0:y1, x0:x1]
    if win.size == 0 or not (win > 0).any():
        return rect
    cols = np.where((win > 0).sum(axis=0) >= 1)[0]
    rows = np.where((win > 0).sum(axis=1) >= 1)[0]
    if len(cols) == 0 or len(rows) == 0:
        return rect
    pad = max(2, _r((rows[-1] - rows[0] + 1) * margin))
    nx0 = max(x0, x0 + int(cols[0]) - pad)
    nx1 = min(x1, x0 + int(cols[-1]) + 1 + pad)
    ny0 = max(y0, y0 + int(rows[0]) - pad)
    ny1 = min(y1, y0 + int(rows[-1]) + 1 + pad)
    # 詰めすぎて読めなくなるのを避ける
    if nx1 - nx0 < 8 or ny1 - ny0 < 8:
        return rect
    return [nx0 / W, ny0 / H, (nx1 - nx0) / W, (ny1 - ny0) / H]


def widen_left(blank: Optional[np.ndarray], rect: List[float],
               max_pad: float = MAX_PAD) -> List[float]:
    """印刷内容にぶつからない範囲で、欄の左端を左へ広げた矩形を返す。

    白紙様式が無い場合や、すぐ左に印刷内容がある場合は元の矩形のまま返す。
    """
    if blank is None or blank.size == 0:
        return rect
    H, W = blank.shape[:2]
    x, y, w, h = rect
    if not all(np.isfinite(v) for v in (x, y, w, h)):
        return rect
    x0 = _r(x * W)
    y0, y1 = max(0, _r(y * H)), min(H, _r((y + h) * H))
    # 欄が画像の外や端に掛かっている場合は触らない（切り抜きが空になり落ちる）
    if x0 <= 1 or x0 >= W - 1 or y1 - y0 < 4:
        return rect

    gap = max(GAP_MIN, _r((y1 - y0) * GAP_RATIO))
    # 欄の左端のすぐ内側に印刷（「（」など）がある場合は、
    # もともと印刷の際まで測れているので広げない
    inside_win = blank[y0:y1, x0:min(W, x0 + gap)]
    if inside_win.size == 0:
        return rect
    inside = _printed(inside_win)
    if ((inside > 0).sum(axis=0) >= INK_MIN).any():
        return rect

    limit = max(0, x0 - _r(max_pad * W))
    band_win = blank[y0:y1, limit:x0]
    if band_win.size == 0:
        return rect
    col = (_printed(band_win) > 0).sum(axis=0)

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
