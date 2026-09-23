# -*- coding: utf-8 -*-
"""読み取った文字列を、書き込みの見た目と突き合わせて確かめる。

OCR の結果だけを見ていても、正しいのか足りないのかが分からない。
そこで白紙様式との差分（＝書き込みだけ）から

- だいたい何文字書かれているか
- 書き込みが欄の端に接していないか（＝切れていないか）

を見て、読めた文字列と食い違う場合は確信度を下げ、理由を残す。
あわせて、罫線やカッコ由来の記号が先頭・末尾に残っていたら落とす。
"""
import math
import re
from typing import List, Optional, Tuple

import cv2
import numpy as np

from . import checkbox

# 先頭・末尾に残りやすい記号。「→ 対処方針 （」のような印刷を拾ったときに出る。
# 括弧は対応が取れているかどうかで扱いを変えるので別に持つ。
LEAD_MISC = "｜|:：;；,，、。・･_＿=＝~〜/／\\＊*+＋\"'`^>＞→ー―—–-"
TAIL_MISC = "｜|:；;,，_＿=＝~〜/／\\＊*+＋\"'`^>＞→"
OPENERS = "（(「『［[｛{"
CLOSERS = "）)」』］]｝}"
# 符号として意味を持つので、後ろが数字なら落とさない
SIGNS = "+＋-ー―—–"
# これだけで出来ている文字列は、印刷の括弧や罫線を読んだものなので空にする。
# `-`（該当なしの意思表示）や `○` `×` は意味を持つので入れない
NOISE_ONLY = ("（）()「」『』［］[]｛｝{}:：;；,，、。・･_＿=＝~〜/／\\"
              "|｜＊*+＋\"'`^ 　>＞<＜→←")
# 空白の扱いをブラウザ版と揃える（str.strip() と trim() は対象が微妙に違う）
_WS = ("[\t\n\v\f\r \u001c-\u001f\u0085\u00a0\u1680\u2000-\u200a"
       "\u2028\u2029\u202f\u205f\u3000\ufeff]")
RE_WS = re.compile(_WS)
RE_TRIM = re.compile(f"^{_WS}+|{_WS}+$")

# 1文字あたりの「インクのある列数 ÷ 行の高さ」。定型サンプル73欄で実測した。
# 中央値は 0.72 だが 0.24〜1.70 とばらつくので、**幅を持たせて明らかな食い違いだけ**を拾う。
# 狭く見積もりすぎると、正しく読めている欄にまで警告が出て確認の邪魔になる。
DENSITY_MAX = 1.70          # 1文字がこれ以上の幅を占めることは稀
DENSITY_MIN = 0.35          # 1文字がこれ未満ということも稀
SHORT_RATIO = 0.8           # 見込みの下限をさらに下回ったら「読み切れていない」
LONG_MARGIN = 2             # 見込みの上限をこれ以上超えたら「余計なものを拾った」
MIN_EXPECT = 3              # 見込みがこれ未満の欄では判定しない
# 1文字ぶんにも満たない書き込みしか無ければ「記入なし」とみなす
EMPTY_DENSITY = 0.25
EMPTY_PENALTY = 0.35
# 端に接しているとみなす画素数
EDGE_PX = 2
PENALTY = 0.8


def _r(v: float) -> int:
    """四捨五入。ブラウザの Math.round と同じ規則にする（Python の round は偶数丸め）。"""
    return int(math.floor(v + 0.5))


def _strip(s: str) -> str:
    """前後の空白を落とす（ブラウザ版と同じ集合）。"""
    return RE_TRIM.sub("", s)


def _unbalanced(text: str, opener: str) -> bool:
    """その開き括弧が閉じられていないか。"""
    close = CLOSERS[OPENERS.index(opener)]
    return text.count(opener) > text.count(close)


def _unmatched_close(text: str, closer: str) -> bool:
    open_ch = OPENERS[CLOSERS.index(closer)]
    return text.count(closer) > text.count(open_ch)


def trim_edges(text: str) -> Tuple[str, List[str]]:
    """先頭・末尾に残った記号を落とす。落とした内容を理由として返す。

    括弧は**対応が取れていないものだけ**落とす。
    `（右）大腿骨頸部骨折` の先頭を落とすと `右）…` となり、
    かえって辞書に当たらなくなるため。
    符号（`-3kg`）と、単独の `-`（「該当なし」の意思表示）は残す。
    """
    if not text:
        return text, []
    original = _strip(text)
    notes = []
    out = original

    # 先頭
    removed = ""
    while out:
        ch = out[0]
        if ch in SIGNS and len(out) > 1 and (out[1].isdigit() or out[1] == "."):
            break                                  # 符号付きの数値
        if ch in CLOSERS and _unmatched_close(out, ch):
            pass
        elif ch in OPENERS and _unbalanced(out, ch):
            pass
        elif ch in LEAD_MISC and ch not in OPENERS and ch not in CLOSERS:
            pass
        else:
            break
        removed += ch
        out = _strip(out[1:])
    if removed:
        notes.append(f"先頭の記号「{removed}」を削除")

    # 末尾
    removed = ""
    while out:
        ch = out[-1]
        if ch in OPENERS and _unbalanced(out, ch):
            pass
        elif ch in CLOSERS and _unmatched_close(out, ch):
            pass
        elif ch in TAIL_MISC and ch not in OPENERS and ch not in CLOSERS:
            pass
        else:
            break
        removed = ch + removed
        out = _strip(out[:-1])
    if removed:
        notes.append(f"末尾の記号「{removed}」を削除")

    out = _strip(out)
    # 記号だけ（印刷の括弧や罫線を読んだもの）なら空にする。
    # ただし `-` や `○` は「該当なし」の意思表示なので残す
    residue = out or original
    if residue and all(ch in NOISE_ONLY for ch in residue):
        return "", notes + [f"記号だけの読み取り「{residue}」を空にしました"]
    if not out:
        return original, []          # 全部消えるなら元のまま（意思表示を消さない）
    return out, notes


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


# 文字欄で白紙側を太らせる幅。枠の判定（5）より**小さくする**。
# 5 にすると罫線やラベルに重なった手書きまで消え、「書き込みが無い」と
# 誤判定して欄をまるごと空にしてしまう（実際にそうなった）
TEXT_BLANK_DILATE = 3


def mark_layer(warped: np.ndarray, blank: Optional[np.ndarray]) -> Optional[np.ndarray]:
    """白紙様式との差分（＝書き込みだけ）。ページに1回作れば足りる。"""
    return checkbox._mark_layer(warped, blank, dilate=TEXT_BLANK_DILATE)


def written_shape(warped: np.ndarray, blank: Optional[np.ndarray],
                  rect: List[float], diff: Optional[np.ndarray] = None) -> Optional[dict]:
    """欄の中の書き込みから、行数・おおよその文字数・端に接しているかを出す。"""
    if diff is None:
        diff = mark_layer(warped, blank)
    if diff is None:
        return None
    H, W = diff.shape
    x, y, w, h = rect
    x0, y0 = max(0, _r(x * W)), max(0, _r(y * H))
    x1, y1 = min(W, _r((x + w) * W)), min(H, _r((y + h) * H))
    if x1 - x0 < 8 or y1 - y0 < 6:
        return None
    win = diff[y0:y1, x0:x1]
    if not (win > 0).any():
        return dict(density=0.0, min_chars=0, max_chars=0, lines=0,
                    cut_left=False, cut_right=False)

    found = _lines(win)
    lines = found or [(0, win.shape[0])]
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
                min_chars=_r(density / DENSITY_MAX),
                max_chars=_r(density / DENSITY_MIN),
                lines=len(found),
                cut_left=bool(len(cols_all) and cols_all[0] <= EDGE_PX),
                cut_right=bool(len(cols_all) and cols_all[-1] >= win.shape[1] - 1 - EDGE_PX))


def check(text: str, warped: np.ndarray, blank: Optional[np.ndarray],
          rect: List[float], charset: str = "",
          diff: Optional[np.ndarray] = None) -> dict:
    """読めた文字列と書き込みの見た目を突き合わせる。

    返り値の `penalty` を確信度に掛け、`notes` を確認画面に出す。
    `charset` のある欄（数字・電話・郵便番号など）は半角が混ざり
    文字の幅が揃わないので、文字数の判定はしない。
    """
    shape = written_shape(warped, blank, rect, diff)
    result = dict(penalty=1.0, notes=[], expected=None, empty_ink=False,
                  read=len(RE_WS.sub("", text or "")))
    if shape is None:
        return result
    result["expected"] = shape["min_chars"]
    read = result["read"]
    lo, hi = shape["min_chars"], shape["max_chars"]

    # 何も書かれていないのに文字が出た場合。罫線や印刷を読んでしまった疑いが濃い。
    # この機能が本来いちばん拾うべき場面なので、文字種による除外もしない。
    if shape["density"] < EMPTY_DENSITY and read >= 1:
        result["empty_ink"] = True
        result["notes"].append("この欄に書き込みが見当たりません（罫線や印刷を読んだ可能性）")
        result["penalty"] *= EMPTY_PENALTY
    elif not charset:
        if lo >= MIN_EXPECT and read < lo * SHORT_RATIO:
            result["notes"].append(
                f"書かれている量に対して読めた文字が少ない（{lo}文字以上あるはずが{read}文字）")
            result["penalty"] *= PENALTY
        elif read > hi + LONG_MARGIN:
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
