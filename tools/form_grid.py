# -*- coding: utf-8 -*-
"""様式の罫線（枠）を検出し、記入欄の位置の基準にする。

意見書は表組みなので、記入する場所は罫線で囲まれたセルか、
下線の上に決まっている。座標を推測するのではなく、
この枠を検出してそこに合わせるのが最も確実。
"""
from typing import Dict, List, Tuple

import cv2
import numpy as np

MIN_H_RATIO = 0.020      # 水平線として認める最小長さ（ページ幅比）
MIN_V_RATIO = 0.022      # 垂直線として認める最小長さ（ページ高さ比）
                         # チェックボックスの辺（約1%）を拾わない長さにする
MERGE_TOL = 4            # 近接する線をまとめる画素数


def _binary(gray: np.ndarray) -> np.ndarray:
    return cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                                 cv2.THRESH_BINARY_INV, 31, 12)


def detect_lines(gray: np.ndarray) -> Tuple[List[tuple], List[tuple]]:
    """水平線・垂直線を検出する。

    返り値は
      水平線: (x0, x1, y)
      垂直線: (x, y0, y1)
    """
    H, W = gray.shape
    bw = _binary(gray)

    hlen = max(12, int(W * MIN_H_RATIO))
    hk = cv2.getStructuringElement(cv2.MORPH_RECT, (hlen, 1))
    hor = cv2.morphologyEx(bw, cv2.MORPH_OPEN, hk)
    hor = cv2.dilate(hor, cv2.getStructuringElement(cv2.MORPH_RECT, (hlen // 3, 1)))

    vlen = max(10, int(H * MIN_V_RATIO))
    vk = cv2.getStructuringElement(cv2.MORPH_RECT, (1, vlen))
    ver = cv2.morphologyEx(bw, cv2.MORPH_OPEN, vk)
    ver = cv2.dilate(ver, cv2.getStructuringElement(cv2.MORPH_RECT, (1, vlen // 3)))

    hlines = []
    cnts, _ = cv2.findContours(hor, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for c in cnts:
        x, y, w, h = cv2.boundingRect(c)
        if w >= hlen and h <= max(4, int(H * 0.004)):
            hlines.append((x, x + w, y + h // 2))

    vlines = []
    cnts, _ = cv2.findContours(ver, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for c in cnts:
        x, y, w, h = cv2.boundingRect(c)
        if h >= vlen and w <= max(4, int(W * 0.004)):
            vlines.append((x + w // 2, y, y + h))

    hlines.sort(key=lambda t: (t[2], t[0]))
    vlines.sort(key=lambda t: (t[0], t[1]))
    return hlines, vlines


def merge_coords(values: List[int], tol: int = MERGE_TOL) -> List[int]:
    """近接する座標をまとめる。"""
    if not values:
        return []
    values = sorted(values)
    out, cur = [], [values[0]]
    for v in values[1:]:
        if v - cur[-1] <= tol:
            cur.append(v)
        else:
            out.append(int(round(sum(cur) / len(cur))))
            cur = [v]
    out.append(int(round(sum(cur) / len(cur))))
    return out


def cells_for_row(hlines, vlines, top: int, bottom: int, W: int) -> List[tuple]:
    """指定の上下境界の間にある縦罫線から、セルの左右境界を作る。"""
    mid = (top + bottom) / 2
    xs = [x for (x, y0, y1) in vlines if y0 <= mid + 2 and y1 >= mid - 2]
    xs = merge_coords(xs)
    if not xs:
        return []
    cells = []
    for i in range(len(xs) - 1):
        if xs[i + 1] - xs[i] < W * 0.02:
            continue
        cells.append((xs[i], top, xs[i + 1], bottom))
    return cells


def build_grid(gray: np.ndarray) -> Dict:
    """罫線から表の構造（行と、その中のセル）を組み立てる。"""
    H, W = gray.shape
    hlines, vlines = detect_lines(gray)
    ys = merge_coords([y for (_, _, y) in hlines])
    rows = []
    for i in range(len(ys) - 1):
        top, bottom = ys[i], ys[i + 1]
        if bottom - top < H * 0.006:
            continue
        cells = cells_for_row(hlines, vlines, top, bottom, W)
        rows.append(dict(top=top, bottom=bottom, cells=cells))
    return dict(width=W, height=H, hlines=hlines, vlines=vlines,
                row_y=ys, rows=rows)


def draw_grid(gray: np.ndarray, grid: Dict) -> np.ndarray:
    """検証用に枠を描画する。"""
    vis = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    for (x0, x1, y) in grid["hlines"]:
        cv2.line(vis, (x0, y), (x1, y), (0, 140, 255), 2)
    for (x, y0, y1) in grid["vlines"]:
        cv2.line(vis, (x, y0), (x, y1), (255, 140, 0), 2)
    for r in grid["rows"]:
        for (x0, top, x1, bottom) in r["cells"]:
            cv2.rectangle(vis, (x0 + 2, top + 2), (x1 - 2, bottom - 2), (0, 200, 0), 1)
    return vis
