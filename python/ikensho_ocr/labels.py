# -*- coding: utf-8 -*-
"""チェック欄の「後ろに書いてある言葉」を読む。

様式を Word で作り直すと、チェック欄の並びは同じでも
**後ろの文字が少し変わる**ことがある（「有」→「あり」など）。
テンプレートに書いてある言葉をそのまま使うと、出力が実物と食い違う。

そこで読み取りのときに枠の右隣を OCR し、実物の言葉を拾う。
読み違えることもあるので、**管理画面から直せる**ようにしてある
（直した内容は `templates/labels/<様式ID>.json` に残る）。
"""
import difflib
import json
import os
import re
import unicodedata
from typing import Dict, List, Optional

import cv2
import numpy as np

from .templates import TEMPLATE_DIR

# 枠の右にどこまでを「その枠の言葉」とみなすか（枠の幅に対する倍率）
LABEL_MAX_WIDTH = 9.0
LABEL_GAP = 0.25        # 枠のすぐ右の空き（枠幅比）。枠線を拾わないため
LABEL_PAD_Y = 0.45      # 上下にどれだけ広げるか（枠の高さ比）
NEXT_BOX_GAP = 0.6      # 次の枠の手前で止めるときの空き（枠幅比）
SAME_ROW = 0.6          # 同じ行とみなす縦のずれ（枠の高さ比）
LABEL_TARGET_H = 48     # OCR に渡すときの文字の高さ（これより小さければ拡大する）
LABEL_PAD = 8           # 切り抜きの周りに足す白の幅。端の文字が切れるのを防ぐ

_KILL = re.compile(r"[\s　:：・.,、。()（）\[\]【】「」]+")
# 四角いチェック欄が文字として読まれたもの。言葉の前後から落とす
_BOXCHAR = re.compile(r"^[口ロ□■☐▢〇○●]+|[口ロ□■☐▢]+$")
# 長音と紛らわしい字。「モニター」が「モニタ一」と読まれる
_DASH = re.compile(r"[ー—–—‐-─―一]")


def normalize(text: str) -> str:
    """見比べるための正規化。全角半角・記号・空白の違いを消す。"""
    if not text:
        return ""
    t = unicodedata.normalize("NFKC", text)
    t = _BOXCHAR.sub("", _KILL.sub("", t))
    return _DASH.sub("ー", t)


def label_rect(box: dict, siblings: List[dict]) -> List[float]:
    """枠の右隣にある言葉の範囲を、正規化座標で返す。

    同じ行の次の枠の手前で止める。次が無ければ枠幅の9倍まで。
    """
    x, y, w, h = box["rect"]
    x0 = x + w * (1.0 + LABEL_GAP)
    right = x + w * (1.0 + LABEL_MAX_WIDTH)
    cy = y + h / 2
    for other in siblings:
        ox, oy, ow, oh = other["rect"]
        if ox <= x:
            continue
        if abs((oy + oh / 2) - cy) > h * SAME_ROW:
            continue
        right = min(right, ox - w * NEXT_BOX_GAP)
    right = min(max(right, x0 + w * 0.8), 1.0)
    y0 = max(0.0, y - h * LABEL_PAD_Y)
    y1 = min(1.0, y + h * (1.0 + LABEL_PAD_Y))
    return [x0, y0, right - x0, y1 - y0]


def label_rects(boxes: List[dict]) -> Dict[str, List[float]]:
    """ページ内の全チェック欄について、言葉の範囲を求める。"""
    return {f"{b['field']}.{b['opt']}": label_rect(b, boxes) for b in boxes}


def prepare(crop: np.ndarray) -> np.ndarray:
    """OCR に渡す前に、小さすぎる切り抜きを拡大して白で縁取る。

    ラベルの文字は高さ20px ほどしかなく、そのままでは読み違えが多い。
    """
    if crop.size == 0:
        return crop
    f = _scale_for(crop)
    if f > 1.0:
        crop = cv2.resize(crop, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)
    return cv2.copyMakeBorder(crop, LABEL_PAD, LABEL_PAD, LABEL_PAD, LABEL_PAD,
                              cv2.BORDER_CONSTANT, value=255)


def group_rows(boxes: List[dict]) -> List[List[dict]]:
    """同じ行に並ぶチェック欄をまとめる。行ごとに1回だけ OCR するため。"""
    rows: List[List[dict]] = []
    for b in sorted(boxes, key=lambda b: (b["rect"][1], b["rect"][0])):
        y, h = b["rect"][1], b["rect"][3]
        cy = y + h / 2
        for row in rows:
            ry, rh = row[0]["rect"][1], row[0]["rect"][3]
            if abs(cy - (ry + rh / 2)) <= rh * SAME_ROW:
                row.append(b)
                break
        else:
            rows.append([b])
    for row in rows:
        row.sort(key=lambda b: b["rect"][0])
    return rows


def read_labels(warped: np.ndarray, boxes: List[dict], ocr,
                only: Optional[set] = None) -> Dict[str, str]:
    """枠の右隣を OCR して、読めた言葉を返す。

    1枠ずつ切り抜くと枠の数だけ OCR を回すことになり遅いうえ、
    2〜3文字だけでは読み違えも多い。**行ごとにまとめて読み**、
    読めた語の位置から、どの枠の言葉かを振り分ける。
    """
    if ocr is None or not hasattr(ocr, "read_tokens"):
        return {}
    H, W = warped.shape[:2]
    out: Dict[str, str] = {}
    for row in group_rows(boxes):
        rects = {f"{b['field']}.{b['opt']}": label_rect(b, boxes) for b in row}
        if only is not None and not any((b["field"], b["opt"]) in only for b in row):
            continue
        x0 = min(r[0] for r in rects.values())
        x1 = max(r[0] + r[2] for r in rects.values())
        y0 = min(r[1] for r in rects.values())
        y1 = max(r[1] + r[3] for r in rects.values())
        px0, py0 = int(round(x0 * W)), int(round(y0 * H))
        px1, py1 = int(round(x1 * W)), int(round(y1 * H))
        if px1 - px0 < 8 or py1 - py0 < 8:
            continue
        crop = warped[max(0, py0):min(H, py1), max(0, px0):min(W, px1)]
        if crop.size == 0:
            continue
        # 四角い枠そのものは「口」と読まれてしまうので、白で塗りつぶしておく
        crop = crop.copy()
        for b in boxes:
            bx, by, bw_, bh_ = b["rect"]
            ex, ey = bw_ * 0.25, bh_ * 0.25
            cx0 = int(round((bx - ex) * W)) - px0
            cy0 = int(round((by - ey) * H)) - py0
            cx1 = int(round((bx + bw_ + ex) * W)) - px0
            cy1 = int(round((by + bh_ + ey) * H)) - py0
            cx0, cy0 = max(0, cx0), max(0, cy0)
            cx1, cy1 = min(crop.shape[1], cx1), min(crop.shape[0], cy1)
            if cx1 > cx0 and cy1 > cy0:
                crop[cy0:cy1, cx0:cx1] = 255
        scale = _scale_for(crop)
        tokens = ocr.read_tokens(prepare(crop))
        if not tokens:
            continue
        # 読めた語を、位置がいちばん重なる枠に振り分ける
        parts: Dict[str, List[tuple]] = {}
        for tk in tokens:
            # prepare() で拡大・縁取りした分を元の座標に戻す
            lx = (tk.x0 - LABEL_PAD) / scale + px0
            rx = (tk.x1 - LABEL_PAD) / scale + px0
            cx = (lx + rx) / 2 / W
            best, cover = None, 0.0
            for key, (rx0, _ry0, rw, _rh) in rects.items():
                lo, hi = rx0, rx0 + rw
                ov = max(0.0, min(hi, rx / W) - max(lo, lx / W))
                if lo <= cx <= hi:
                    ov += rw          # 中心が入っている枠を優先する
                if ov > cover:
                    best, cover = key, ov
            if best:
                parts.setdefault(best, []).append((lx, tk.text))
        for key, items in parts.items():
            items.sort()
            text = normalize("".join(t for _, t in items))
            if text:
                out[key] = text
    return out


def _scale_for(crop: np.ndarray) -> float:
    h = crop.shape[0]
    return min(4.0, LABEL_TARGET_H / max(h, 1)) if h < LABEL_TARGET_H else 1.0


# ---------------------------------------------------------------- 保存と照合

def labels_path(template_id: str) -> str:
    return os.path.join(TEMPLATE_DIR, "labels", f"{template_id}.json")


def load_overrides(template_id: str) -> Dict[str, str]:
    """管理画面で直した言葉。{"field.opt": "言葉"}"""
    path = labels_path(template_id)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return {k: str(v) for k, v in data.items() if isinstance(v, str)}
    except (OSError, ValueError):
        return {}


def save_overrides(template_id: str, labels: Dict[str, str]) -> str:
    path = labels_path(template_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    clean = {k: v.strip() for k, v in labels.items() if isinstance(v, str) and v.strip()}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(clean, fh, ensure_ascii=False, indent=1, sort_keys=True)
    return path


def similarity(a: str, b: str) -> float:
    """2つの言葉がどれだけ似ているか 0..1。"""
    a, b = normalize(a), normalize(b)
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


# 「読めた言葉が定義と違う」と言い切るための条件。
# ラベルは小さく、OCR は 4割ほど読み違える。安易に読み取りを採用すると
# かえって出力が壊れるので、**定義とも他の選択肢とも似ていないとき**だけ疑う。
CHANGED_MAX_SIM = 0.5    # 定義との似かた
CHANGED_MIN_LEN = 3      # これより短い言葉は読み違えが多いので疑わない


def resolve(field_id: str, opt: int, expected: str, read: Optional[str],
            overrides: Dict[str, str],
            siblings: Optional[List[str]] = None) -> dict:
    """その枠に使う言葉を決める。

    優先順位は **管理画面で直した言葉 > 定義の言葉**。
    読めた言葉はそのまま採らず、**定義と食い違うときの合図**として使う。
    OCR がラベルを読み違える率は実測で4割あり、そのまま採ると
    出力がかえって壊れるため。食い違いは `changed` を立てて画面に出す。
    """
    key = f"{field_id}.{opt}"
    out = dict(word=expected, source="定義", expected=expected, read=read or "",
               changed=False)
    fixed = overrides.get(key)
    if fixed:
        out.update(word=fixed, source="修正")
        return out
    if not read or len(normalize(read)) < CHANGED_MIN_LEN:
        return out
    nr, ne = normalize(read), normalize(expected)
    # 隣の語まで一緒に読めてしまうことがある。定義の言葉を含むなら同じとみなす
    if ne and (ne in nr or nr in ne):
        return out
    if similarity(read, expected) > CHANGED_MAX_SIM:
        return out
    # 同じ項目の他の選択肢に近いなら、振り分けを誤っただけとみなす
    for other in (siblings or []):
        no = normalize(other)
        if other == expected or not no:
            continue
        if no in nr or similarity(read, other) > CHANGED_MAX_SIM:
            return out
    out.update(changed=True, note="定義と違う言葉が読めました。確かめてください")
    return out


def apply_words(entry: dict, options: List[str], words: List[str]) -> None:
    """項目の値を、実物の言葉（または管理画面で直した言葉）に置き換える。

    出力の JSON はチェックの**言葉**が要なので、値そのものを差し替える。
    """
    if list(words) == list(options):
        return
    table = {o: w for o, w in zip(options, words)}
    value = entry.get("value")
    if isinstance(value, str):
        entry["value"] = table.get(value, value)
    elif isinstance(value, list):
        entry["value"] = [table.get(v, v) for v in value]
