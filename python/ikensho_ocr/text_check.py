# -*- coding: utf-8 -*-
"""読み取った文字列を、書き込みの見た目と突き合わせて確かめる。

OCR の結果だけを見ていても、正しいのか足りないのかが分からない。
そこで白紙様式との差分（＝書き込みだけ）から

- だいたい何文字書かれているか
- 書き込みが欄の端に接していないか（＝切れていないか）

を見て、読めた文字列と食い違う場合は確信度を下げ、理由を残す。
あわせて、罫線やカッコ由来の記号が先頭・末尾に残っていたら落とす。
"""
import re
from typing import List, Optional, Tuple

import cv2
import numpy as np

from . import checkbox

# 先頭に残りやすい記号。「→ 対処方針 （」のような印刷を拾ったときに出る
LEAD_JUNK = "（(｜|[]{}「」『』:：;；,，、。・･_＿=＝~〜/／\\＊*+＋\"'`^ 　>＞→ー―—–-"
# 末尾に残りやすい記号。「。」「、」や長音は本文のことがあるので落とさない
TAIL_JUNK = "｜|[]{}「『:；;,，_＿=＝~〜/／\\＊*+＋\"'`^ 　>＞→"

# 1文字あたりの「インクのある列数 ÷ 行の高さ」。定型サンプル73欄で実測した。
# 中央値は 0.72 だが 0.24〜1.70 とばらつくので、**幅を持たせて明らかな食い違いだけ**を拾う。
# 狭く見積もりすぎると、正しく読めている欄にまで警告が出て確認の邪魔になる。
DENSITY_MAX = 1.70          # 1文字がこれ以上の幅を占めることは稀
DENSITY_MIN = 0.35          # 1文字がこれ未満ということも稀
SHORT_RATIO = 0.8           # 見込みの下限をさらに下回ったら「読み切れていない」
LONG_MARGIN = 2             # 見込みの上限をこれ以上超えたら「余計なものを拾った」
MIN_EXPECT = 3              # 見込みがこれ未満の欄では判定しない
# 端に接しているとみなす画素数
EDGE_PX = 2
PENALTY = 0.8


def trim_edges(text: str) -> Tuple[str, List[str]]:
    """先頭・末尾に残った記号を落とす。落とした内容を理由として返す。"""
    if not text:
        return text, []
    notes = []
    out = text.strip()
    head = out.lstrip(LEAD_JUNK)
    if head != out:
        notes.append(f"先頭の記号「{out[:len(out) - len(head)]}」を削除")
        out = head
    tail = out.rstrip(TAIL_JUNK)
    if tail != out:
        notes.append(f"末尾の記号「{out[len(tail):]}」を削除")
        out = tail
    # 対になっていない閉じカッコは印刷のカッコを拾ったもの
    while out.endswith(("）", ")")) and out.count("（") + out.count("(") < \
            out.count("）") + out.count(")"):
        notes.append("末尾の閉じカッコを削除")
        out = out[:-1].rstrip()
    return out.strip(), notes


def _lines(mask: np.ndarray) -> List[Tuple[int, int]]:
    """行のかたまり（上端, 下端）を返す。"""
    rows = (mask > 0).sum(axis=1)
    on = rows >= 2
    out, start = [], None
    for i, v in enumerate(on):
        if v and start is None:
            start = i
        elif not v and start is not None:
            if i - start >= 3:
                out.append((start, i))
            start = None
    if start is not None and len(on) - start >= 3:
        out.append((start, len(on)))
    return out


def written_shape(warped: np.ndarray, blank: Optional[np.ndarray],
                  rect: List[float]) -> Optional[dict]:
    """欄の中の書き込みから、行数・おおよその文字数・端に接しているかを出す。"""
    diff = checkbox._mark_layer(warped, blank)
    if diff is None:
        return None
    H, W = diff.shape
    x, y, w, h = rect
    x0, y0 = max(0, int(round(x * W))), max(0, int(round(y * H)))
    x1, y1 = min(W, int(round((x + w) * W))), min(H, int(round((y + h) * H)))
    if x1 - x0 < 8 or y1 - y0 < 6:
        return None
    win = diff[y0:y1, x0:x1]
    if not (win > 0).any():
        return dict(density=0.0, min_chars=0, max_chars=0, lines=0,
                    cut_left=False, cut_right=False)

    lines = _lines(win) or [(0, win.shape[0])]
    # 行ごとに「インクのある列数 ÷ 行の高さ」を足す。
    # 端から端までの幅ではなく列数を数えるのは、
    # 欄の中の空きや罫線の残りで水増しされないようにするため。
    density = 0.0
    for top, bottom in lines:
        band = win[top:bottom]
        cols = np.where((band > 0).sum(axis=0) >= 1)[0]
        lh = max(bottom - top, 1)
        if len(cols) == 0 or lh < 6:
            continue
        density += len(cols) / lh

    cols_all = np.where((win > 0).sum(axis=0) >= 2)[0]
    return dict(density=density,
                min_chars=int(round(density / DENSITY_MAX)),
                max_chars=int(round(density / DENSITY_MIN)),
                lines=len(lines),
                cut_left=bool(len(cols_all) and cols_all[0] <= EDGE_PX),
                cut_right=bool(len(cols_all) and cols_all[-1] >= win.shape[1] - 1 - EDGE_PX))


def check(text: str, warped: np.ndarray, blank: Optional[np.ndarray],
          rect: List[float], charset: str = "") -> dict:
    """読めた文字列と書き込みの見た目を突き合わせる。

    返り値の `penalty` を確信度に掛け、`notes` を確認画面に出す。
    `charset` のある欄（数字・電話・郵便番号など）は半角が混ざり
    文字の幅が揃わないので、文字数の判定はしない。
    """
    shape = written_shape(warped, blank, rect)
    result = dict(penalty=1.0, notes=[], expected=None,
                  read=len(re.sub(r"\s", "", text or "")))
    if shape is None:
        return result
    result["expected"] = shape["min_chars"]
    read = result["read"]
    lo, hi = shape["min_chars"], shape["max_chars"]

    if not charset:
        if lo >= MIN_EXPECT and read < lo * SHORT_RATIO:
            result["notes"].append(
                f"書かれている量に対して読めた文字が少ない（{lo}文字以上あるはずが{read}文字）")
            result["penalty"] *= PENALTY
        elif hi >= 1 and read > hi + LONG_MARGIN:
            result["notes"].append(
                f"書かれている量より読めた文字が多い（多くても{hi}文字のはずが{read}文字）")
            result["penalty"] *= PENALTY
    if shape["cut_left"]:
        result["notes"].append("記入が欄の左端に接しています（先頭が切れている可能性）")
        result["penalty"] *= 0.9
    if shape["cut_right"]:
        result["notes"].append("記入が欄の右端に接しています（末尾が切れている可能性）")
        result["penalty"] *= 0.9
    return result
