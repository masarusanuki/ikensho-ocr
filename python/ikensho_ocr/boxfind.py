# -*- coding: utf-8 -*-
"""テンプレートの座標に頼らず、ページの中から□を見つける。

様式を Word で作り直すと、**質問文はそのままでも回答項目（選択肢）が
増えたり減ったり位置がずれたり**する。テンプレートの座標だけを見ていると、
増えた選択肢は最初から存在しないことになってしまう。

そこでページ画像から□そのものを探し、テンプレートに無い□を
「増えた選択肢」として拾えるようにする。

**実測（seigo2 の3通・□ 558 個）**

  - 横線の対だけ           84.8%
  - 縦線の対を足す         92.8%   ← 既定
  - 外側の輪郭（塗り潰し）  足しても当たりは増えなかった（14個検出・新規0）

見つからない残りは、**印が濃くて枠線が印に埋もれた□**が中心で、
つまり「答えが書いてある□」ほど見つけにくい。だからこれは
テンプレートの座標の**置き換えではなく、上乗せ**として使う。
座標のある□は今まで通り必ず読み、ここで見つけた□は
テンプレートに無いものだけを追加の選択肢として扱う。

検出数は既知の□の数倍出る（漢字の画も四角に見えるため）。
後段で「右にラベルの文字が読めること」を条件にして絞る前提。
"""
from typing import List, Tuple

import cv2
import numpy as np

# 200dpi 相当（テンプレート座標系）での□の一辺
SIDE_MIN = 14
SIDE_MAX = 27
# 辺とみなす最短の長さ。短くすると漢字の画を拾いすぎる
RUN = 13
# 同じ□とみなす距離
SAME = 8

Rect = Tuple[int, int, int, int]


def _binarize(gray: np.ndarray) -> np.ndarray:
    return cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                                 cv2.THRESH_BINARY_INV, 25, 10)


def _segments(bw: np.ndarray, kernel: Tuple[int, int], long_axis: int) -> List[Tuple[int, int, int]]:
    """指定方向に伸びた線分を (x, y, 長さ) で返す。"""
    line = cv2.morphologyEx(bw, cv2.MORPH_OPEN, np.ones(kernel, np.uint8))
    n, _, stats, _ = cv2.connectedComponentsWithStats(line, 8)
    out = []
    for i in range(1, n):
        x, y, w, h, _ = stats[i]
        length, thick = (w, h) if long_axis == 0 else (h, w)
        if SIDE_MIN <= length <= SIDE_MAX and thick <= 4:
            out.append((x, y, length))
    return out


def _from_horizontals(bw: np.ndarray, vert: np.ndarray) -> List[Rect]:
    """上辺と下辺の対から□を作る。空の□に強い。"""
    tops = sorted(_segments(bw, (1, RUN), 0), key=lambda t: (t[0], t[1]))
    by_x = {}
    for x, y, w in tops:
        by_x.setdefault(x // 4, []).append((x, y, w))
    out: List[Rect] = []
    for key, group in by_x.items():
        cand = group + by_x.get(key - 1, []) + by_x.get(key + 1, [])
        for x1, y1, w1 in group:
            for x2, y2, w2 in cand:
                d = y2 - y1
                if not (SIDE_MIN <= d <= SIDE_MAX):
                    continue
                if abs(x2 - x1) > 3 or abs(w2 - w1) > 4:
                    continue
                s = max(w1, w2)
                left = vert[y1:y1 + d, max(x1 - 2, 0):x1 + 3]
                right = vert[y1:y1 + d, max(x1 + s - 3, 0):x1 + s + 2]
                if left.size == 0 or right.size == 0 or left.max() == 0 or right.max() == 0:
                    continue
                out.append((x1, y1, s, d))
    return out


def _from_verticals(bw: np.ndarray) -> List[Rect]:
    """左辺と右辺の対から□を作る。印で上辺が消えた□を拾う。"""
    segs = sorted(_segments(bw, (RUN, 1), 1), key=lambda s: (s[1], s[0]))
    out: List[Rect] = []
    for i, (x1, y1, h1) in enumerate(segs):
        for x2, y2, h2 in segs[i + 1:]:
            if y2 - y1 > 4:
                break
            d = x2 - x1
            if not (SIDE_MIN <= d <= SIDE_MAX) or abs(h2 - h1) > 5:
                continue
            out.append((x1, min(y1, y2), d, max(h1, h2)))
    return out


def _dedupe(rects: List[Rect]) -> List[Rect]:
    rects = sorted(rects, key=lambda r: (r[1], r[0]))
    kept: List[Rect] = []
    for r in rects:
        if any(abs(r[0] - k[0]) < SAME and abs(r[1] - k[1]) < SAME for k in kept):
            continue
        kept.append(r)
    return kept


def find_boxes(warped: np.ndarray) -> List[Rect]:
    """位置合わせ済みのページから□の候補を返す（x, y, 幅, 高さ）。

    偽物を多く含む。テンプレートに無い□を拾う用途にだけ使うこと。
    """
    bw = _binarize(warped)
    vert = cv2.morphologyEx(bw, cv2.MORPH_OPEN, np.ones((RUN, 1), np.uint8))
    return _dedupe(_from_horizontals(bw, vert) + _from_verticals(bw))


def overlaps(a: Rect, b: Rect) -> bool:
    """中心どうしが近ければ同じ□とみなす。"""
    ax, ay = a[0] + a[2] / 2, a[1] + a[3] / 2
    bx, by = b[0] + b[2] / 2, b[1] + b[3] / 2
    return abs(ax - bx) < SAME and abs(ay - by) < SAME


# --- テンプレートに無い□を「増えた選択肢」として拾う -------------------

# 同じ質問の選択肢とみなす縦のずれ（□の高さに対する割合）
ROW_TOL = 0.8
# 同じ質問とみなす横の距離（ページ幅に対する割合）。
# これより離れた□は別の質問のものとみなして捨てる
NEAR_X = 0.22


def _rects_px(boxes: List[dict], W: int, H: int) -> List[Rect]:
    out = []
    for b in boxes:
        rx, ry, rw, rh = b["rect"]
        out.append((int(round(rx * W)), int(round(ry * H)),
                    max(3, int(round(rw * W))), max(3, int(round(rh * H)))))
    return out


def extra_boxes(warped: np.ndarray, template_boxes: List[dict]) -> List[dict]:
    """テンプレートに無い□を探し、近くの質問の選択肢として返す。

    返すのは template_boxes と同じ形の辞書（field / opt / rect）に
    `extra: True` を足したもの。opt はその質問の最大値の次から振る。

    どの質問にも寄せられない□（表の罫線の交点、漢字の画など）は捨てる。
    増やしすぎると単一選択の判定を壊すので、**拾えないより拾いすぎない**方へ倒す。
    """
    if not template_boxes:
        return []
    H, W = warped.shape[:2]
    known = _rects_px(template_boxes, W, H)
    found = find_boxes(warped)
    side = float(np.median([r[2] for r in known]))
    row_tol = side * ROW_TOL
    near_x = W * NEAR_X

    max_opt: dict = {}
    for b in template_boxes:
        max_opt[b["field"]] = max(max_opt.get(b["field"], -1), int(b["opt"]))

    out: List[dict] = []
    for r in found:
        if any(overlaps(r, k) for k in known):
            continue
        cx, cy = r[0] + r[2] / 2, r[1] + r[3] / 2
        best, best_d = None, None
        for b, k in zip(template_boxes, known):
            kx, ky = k[0] + k[2] / 2, k[1] + k[3] / 2
            if abs(ky - cy) > row_tol:
                continue
            d = abs(kx - cx)
            if d > near_x:
                continue
            if best_d is None or d < best_d:
                best, best_d = b, d
        if best is None:
            continue
        fid = best["field"]
        max_opt[fid] += 1
        out.append(dict(field=fid, opt=max_opt[fid],
                        rect=[r[0] / W, r[1] / H, r[2] / W, r[3] / H],
                        extra=True))
    return out
