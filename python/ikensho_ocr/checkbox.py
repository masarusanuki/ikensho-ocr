# -*- coding: utf-8 -*-
"""チェックボックスの記入判定。

印刷された枠線を除いた「内部のインク量」でチェックの有無を判定する。
OCR を使わないため、手書き・印刷・スキャンいずれでも安定して読める。
"""
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

# 内部インク率の判定しきい値
EMPTY_MAX = 0.10     # これ未満なら未チェック
FILLED_MIN = 0.28    # これ以上ならチェック済み


# 枠を丸で囲む記入への対応
HALO_MARGIN = 0.55       # 枠の外側どこまでを「丸」とみなすか（枠サイズ比）
HALO_EXCESS_MIN = 0.06   # 同一項目の他の選択肢より、これだけ濃ければ丸印とみなす

# 白紙様式との差分によるマーク検出
MARK_MARGIN = 0.45       # 参考値 mark を測る窓の広さ（枠サイズ比）
MARK_EMPTY_MAX = 0.012   # 参考値 mark の目安（判定には使わない）
MARK_FILLED_MIN = 0.030
BLANK_DILATE = 5         # 白紙側のインクを太らせる幅（重ね合わせのずれを吸収）
# **文字欄では 3 を使う**（`text_check.TEXT_BLANK_DILATE`）。
# 枠の判定では 5 にして印刷の枠線を確実に消したいが、同じ値を文字欄に使うと
# 罫線やラベルに重なった手書きまで消え、「書き込みが無い」と誤判定する。

# 判定に使う3つの見方（正解データ100通・18,600枠で調整）
#   ink : 枠の中の書き込み量。ふつうのレ点・×・塗りつぶしはここで決まる
#   ring: 枠の外周の書き込み量。枠を丸で囲む書き方を拾う
#   out : 枠の右下にずれた印。枠外にはみ出した書き方を拾う
INK_EMPTY_MAX = 0.02     # 枠内の書き込みがこれ未満なら未記入
INK_FILLED_MIN = 0.06    # これ以上なら記入あり（境界は 0.04）
RING_EMPTY_MAX = 0.10    # 枠の外周の書き込み（丸囲み）
RING_FILLED_MIN = 0.30   # （境界は 0.20）
RING_BIAS_MAX = 0.50     # 外周のインクが片側に寄っていたら丸ではない（隣の字）
OUT_EMPTY_MAX = 0.015    # 枠の右下のはみ出し（境界は 0.03）
OUT_FILLED_MIN = 0.045
OUT_EDGE_EMPTY_MAX = 0.010   # 枠の中とつながっているか（境界は 0.02）
OUT_EDGE_FILLED_MIN = 0.030

# 二重線で消した印（＝未チェック扱い）
STRIKE_BANDS_MIN = 1     # 枠を左右に突き抜ける長い横線がこの本数以上
STRIKE_ALL_BANDS_MIN = 2  # 突き抜けを問わない長い横線の本数（二重線なので2本）
STRIKE_LEN_MIN = 1.8     # 同じ項目に他の印があるとき、線の長さ（枠幅比）
STRIKE_LEN_ALONE = 2.2   # ないとき
STRIKE_SIDE = 0.3        # 枠の左右どこまで外に出ていれば「突き抜けた」とみなすか


@dataclass
class BoxReading:
    field: str
    opt: int
    fill: float           # 内部インク率 0..1
    halo: float           # 枠のすぐ外側のインク率 0..1（丸囲み検出用）
    mark: float           # 白紙様式との差分から得た記入量 0..1（参考値）
    score: float          # 上記を統合した記入の強さ 0..1
    checked: bool
    confidence: float     # 0..1
    rect: List[float]
    circled: bool = False
    method: str = "fill"  # 判定に使った指標
    ink: float = 0.0      # 枠の中の書き込み量 0..1
    ring: float = 0.0     # 枠の外周の書き込み量 0..1（丸囲み）
    ring_bias: float = 0.0    # 外周インクの左右の偏り 0..1（大きいほど隣の字くさい）
    out_mark: float = 0.0     # 枠の右下にずれた書き込み量 0..1
    out_edge: float = 0.0     # 枠の右端の書き込み量 0..1（はみ出しは枠とつながる）
    strike_len: float = 0.0   # 枠を横切る長い横線の長さ（枠幅比）
    strike_bands: int = 0     # そのうち枠を左右に突き抜けた本数
    strike_all: int = 0       # 突き抜けを問わない本数
    struck: bool = False      # 二重線で消されている


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


def _halo_ratio(bw: np.ndarray, x: int, y: int, w: int, h: int) -> float:
    """枠のすぐ外側のインク率。枠を丸で囲む記入方式を拾うために使う。"""
    mx, my = int(round(w * HALO_MARGIN)), int(round(h * HALO_MARGIN))
    H, W = bw.shape
    ox0, oy0 = max(0, x - mx), max(0, y - my)
    ox1, oy1 = min(W, x + w + mx), min(H, y + h + my)
    outer = bw[oy0:oy1, ox0:ox1] > 0
    if outer.size == 0:
        return 0.0
    inner_mask = np.zeros_like(outer, dtype=bool)
    iy0, ix0 = y - oy0, x - ox0
    inner_mask[max(0, iy0):iy0 + h, max(0, ix0):ix0 + w] = True
    ring = outer[~inner_mask]
    return float(ring.mean()) if ring.size else 0.0


def _mark_layer(warped: np.ndarray, blank: Optional[np.ndarray],
                dilate: int = BLANK_DILATE) -> Optional[np.ndarray]:
    """白紙様式との差分をとり、手書きのマークだけを残した2値画像を作る。

    枠線・ラベル・説明文といった印刷内容が消えるため、
    枠からはみ出したレ点や枠を囲む丸印も素直に拾える。

    `dilate` は白紙側のインクを太らせる幅。**用途によって変える。**
    枠の判定は 5（印刷の枠線を確実に消す）、文字欄は 3
    （太らせすぎると罫線に重なった手書きまで消える）。
    """
    if blank is None or blank.shape != warped.shape:
        return None
    scan = _binarize(warped)
    base = _binarize(blank)
    # 位置ずれの許容のため、白紙側のインクを少し太らせてから引く
    d = max(1, int(dilate))
    base = cv2.dilate(base, np.ones((d, d), np.uint8), iterations=1)
    diff = cv2.bitwise_and(scan, cv2.bitwise_not(base))
    # 孤立したノイズ点を除去
    diff = cv2.morphologyEx(diff, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    return diff


def _mark_ratio(diff: np.ndarray, x: int, y: int, w: int, h: int) -> float:
    """枠とその周辺に残った書き込み量。"""
    mx, my = int(round(w * MARK_MARGIN)), int(round(h * MARK_MARGIN))
    H, W = diff.shape
    x0, y0 = max(0, x - mx), max(0, y - my)
    x1, y1 = min(W, x + w + mx), min(H, y + h + my)
    win = diff[y0:y1, x0:x1]
    if win.size == 0:
        return 0.0
    return float((win > 0).mean())



def _ink_ratio(diff: np.ndarray, x: int, y: int, w: int, h: int) -> float:
    """枠の中だけの書き込み量。隣の手書きを拾わない。"""
    H, W = diff.shape
    win = diff[max(0, y):min(H, y + h), max(0, x):min(W, x + w)]
    return float((win > 0).mean()) if win.size else 0.0


def _ring_ratio(diff: np.ndarray, x: int, y: int,
                w: int, h: int) -> Tuple[float, float]:
    """枠の外周の書き込み量と、その左右の偏り。

    枠を丸で囲む書き方は外周がぐるりと濃くなる。
    隣の字を拾っただけなら片側に偏るので、偏りで見分ける。
    """
    mx, my = int(round(w * MARK_MARGIN)), int(round(h * MARK_MARGIN))
    H, W = diff.shape
    rx0, ry0 = max(0, x - mx), max(0, y - my)
    rx1, ry1 = min(W, x + w + mx), min(H, y + h + my)
    win = diff[ry0:ry1, rx0:rx1]
    if win.size == 0:
        return 0.0, 0.0
    inner = diff[max(0, y):min(H, y + h), max(0, x):min(W, x + w)]
    total = float((win > 0).sum())
    inner_sum = float((inner > 0).sum()) if inner.size else 0.0
    area = max(1, win.size - (inner.size if inner.size else 0))
    cx = x + w / 2 - rx0
    left = float((win[:, :max(1, int(cx))] > 0).sum())
    bias = abs(left - (total - left)) / max(total, 1.0)
    return (total - inner_sum) / area, bias


def _outside_ratio(diff: np.ndarray, x: int, y: int,
                   w: int, h: int) -> Tuple[float, float]:
    """枠の右下にずれて書かれた印を拾う。

    枠外はみ出しの印は枠の右端に掛かったまま外へ伸びる。
    隣の手書きは枠に触れないので、枠の右端の濃さも併せて見る。
    """
    H, W = diff.shape
    qx0, qy0 = max(0, x + int(w * 0.35)), max(0, y - int(h * 0.1))
    qx1, qy1 = min(W, x + int(w * 1.6)), min(H, y + int(h * 1.4))
    q = diff[qy0:qy1, qx0:qx1]
    out = float((q > 0).mean()) if q.size else 0.0
    tx0, tx1 = max(0, x + int(w * 0.6)), min(W, x + w)
    t = diff[max(0, y):min(H, y + h), tx0:tx1]
    edge = float((t > 0).mean()) if t.size else 0.0
    return out, edge


def _count_bands(rows: np.ndarray, need: float) -> int:
    """しきい値を超える行のかたまりの数を数える。"""
    bands = 0
    prev = False
    for v in rows >= need:
        if v and not prev:
            bands += 1
        prev = bool(v)
    return bands


def _strike_lines(bw: np.ndarray, blank_bw: Optional[np.ndarray],
                  x: int, y: int, w: int, h: int) -> Tuple[float, int, int]:
    """枠を横切る「手書きの長い横線」の長さと本数。

    二重線で消した箇所を見つけるために使う。差分画像では線が枠線や文字と
    重なった部分が消えて途切れるので、元画像から横線だけを取り出し、
    白紙様式にも同じ線があるもの（罫線）を引いて求める。
    """
    if blank_bw is None:
        return 0.0, 0, 0
    H, W = bw.shape
    by0, by1 = max(0, y - h), min(H, y + h * 2)
    bx0, bx1 = max(0, x - int(w * 1.8)), min(W, x + int(w * 2.8))
    band = bw[by0:by1, bx0:bx1]
    bband = blank_bw[by0:by1, bx0:bx1]
    if band.size == 0 or band.shape != bband.shape:
        return 0.0, 0, 0
    ker = cv2.getStructuringElement(cv2.MORPH_RECT, (max(6, int(w * 1.3)), 1))
    lines = cv2.morphologyEx(band, cv2.MORPH_OPEN, ker)
    # 罫線は重ね合わせのずれで数ピクセル動く。縦に厚く膨らませて確実に消す
    plines = cv2.dilate(cv2.morphologyEx(bband, cv2.MORPH_OPEN, ker),
                        np.ones((9, 5), np.uint8))
    written = cv2.bitwise_and(lines, cv2.bitwise_not(plines))
    ry0 = max(0, y - by0 + int(h * 0.12))
    ry1 = min(written.shape[0], y - by0 + h - int(h * 0.12))
    seg = written[ry0:ry1]
    if seg.size == 0:
        return 0.0, 0, 0
    rows = (seg > 0).sum(axis=1)
    need = w * 1.2
    bands_all = _count_bands(rows, need)
    # 枠の左右どちらにも突き抜けている行だけに絞る。
    # 枠の中だけを塗りつぶした印を二重線と取り違えないため。
    lx = max(1, x - bx0 - int(w * STRIKE_SIDE))
    rx = min(seg.shape[1] - 1, x - bx0 + w + int(w * STRIKE_SIDE))
    both = (seg[:, :lx] > 0).any(axis=1) & (seg[:, rx:] > 0).any(axis=1)
    rows = np.where(both, rows, 0)
    return float(rows.max() / max(w, 1)), _count_bands(rows, need), bands_all


def _resolve_strikes(rs: List[BoxReading]) -> None:
    """二重線で消された印を未チェックに戻す。

    同じ項目に他の印があるとき（＝書き直し）は、より緩く見る。
    """
    by_field: Dict[str, List[BoxReading]] = {}
    for r in rs:
        by_field.setdefault(r.field, []).append(r)
    for group in by_field.values():
        for r in group:
            if (not r.checked or r.strike_bands < STRIKE_BANDS_MIN
                    or r.strike_all < STRIKE_ALL_BANDS_MIN):
                continue
            others = sum(1 for o in group if o is not r and o.checked)
            need = STRIKE_LEN_MIN if others else STRIKE_LEN_ALONE
            if r.strike_len >= need:
                r.struck = True
                r.checked = False
                r.score = round(min(r.score, 0.45), 4)
                r.confidence = _score_confidence(r.score)


def _unit(value: float, lo: float, hi: float) -> float:
    """lo で 0、hi で 1 になるように 0..1 へ写す。"""
    if hi <= lo:
        return 0.0
    return max(0.0, min(1.0, (value - lo) / (hi - lo)))


def _combined_score(fill: float, ink: float = 0.0, ring: float = 0.0,
                    ring_bias: float = 1.0, out_mark: float = 0.0,
                    out_edge: float = 0.0, has_diff: bool = False) -> float:
    """記入の強さを 0..1 で表す。0.5 以上を「印あり」とする。

    書き方によって現れる場所が違うので、4つの見方のうち一番強いものを採る。
      枠の中に収まった印  → fill / ink
      枠を丸で囲んだ印    → ring（ただし左右に偏っていたら隣の字とみなす）
      枠外にはみ出した印  → out（枠の右端とつながっているものだけ）
    """
    s = _unit(fill, EMPTY_MAX, FILLED_MIN)
    if has_diff:
        s = max(s, _unit(ink, INK_EMPTY_MAX, INK_FILLED_MIN))
        if ring_bias <= RING_BIAS_MAX:
            s = max(s, _unit(ring, RING_EMPTY_MAX, RING_FILLED_MIN))
        s = max(s, min(_unit(out_mark, OUT_EMPTY_MAX, OUT_FILLED_MIN),
                       _unit(out_edge, OUT_EDGE_EMPTY_MAX, OUT_EDGE_FILLED_MIN)))
    return s


def _score_confidence(score: float) -> float:
    """0.5 を境界として、そこからの距離を確信度にする。"""
    return round(min(1.0, 0.45 + abs(score - 0.5) * 1.10), 3)


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


def _detect_circled(rs: List[BoxReading]) -> None:
    """枠を丸で囲む記入を検出する。

    枠の内側が薄くても、同じ項目の他の選択肢と比べて枠の外周が明らかに濃ければ
    「丸で囲まれた」とみなす。ラベル文字は全選択肢に等しく乗るので、
    中央値との差を見ることで文字の影響を打ち消せる。
    """
    if len(rs) < 2:
        return
    if rs[0].method == "diff":
        return                      # 差分方式では丸囲みもそのまま検出できる
    if any(r.checked for r in rs):
        return                      # 既に検出できているなら丸囲み判定は不要
    halos = sorted(r.halo for r in rs)
    base = halos[len(halos) // 2]
    best = max(rs, key=lambda r: r.halo)
    others = sorted((r.halo for r in rs if r is not best), reverse=True)
    runner_up = others[0] if others else 0.0
    if best.halo - base < HALO_EXCESS_MIN or best.halo - runner_up < HALO_EXCESS_MIN / 2:
        return
    best.circled = True
    best.checked = True
    excess = best.halo - max(base, runner_up)
    best.confidence = round(min(0.85, 0.40 + excess / 0.12 * 0.45), 3)
    # 丸囲みは枠内インク率では説明できないため、判定用のスコアを底上げする
    best.score = max(best.score, 0.55)


def read_boxes(warped: np.ndarray, boxes: List[dict],
               blank: Optional[np.ndarray] = None) -> List[BoxReading]:
    """テンプレート座標系に合わせた画像から全チェックボックスを読み取る。

    白紙様式(blank)を渡すと差分でマークを抽出するため精度が上がる。
    渡せない場合は枠内インク率のみで判定する。
    """
    bw = _binarize(warped)
    diff = _mark_layer(warped, blank)
    blank_bw = (_binarize(blank)
                if blank is not None and blank.shape == warped.shape else None)
    H, W = warped.shape
    out = []
    for b in boxes:
        rx, ry, rw, rh = b["rect"]
        x, y = int(round(rx * W)), int(round(ry * H))
        w, h = max(3, int(round(rw * W))), max(3, int(round(rh * H)))
        x = max(0, min(x, W - w))
        y = max(0, min(y, H - h))
        fill = _fill_ratio(bw, x, y, w, h)
        halo = _halo_ratio(bw, x, y, w, h)
        has_diff = diff is not None
        mark = _mark_ratio(diff, x, y, w, h) if has_diff else 0.0
        ink = _ink_ratio(diff, x, y, w, h) if has_diff else 0.0
        ring, bias = _ring_ratio(diff, x, y, w, h) if has_diff else (0.0, 0.0)
        om, oe = _outside_ratio(diff, x, y, w, h) if has_diff else (0.0, 0.0)
        slen, sbands, sall = _strike_lines(bw, blank_bw, x, y, w, h)
        score = _combined_score(fill, ink, ring, bias, om, oe, has_diff)
        out.append(BoxReading(field=b["field"], opt=b["opt"], fill=round(fill, 4),
                              halo=round(halo, 4), mark=round(mark, 4),
                              ink=round(ink, 4), ring=round(ring, 4),
                              ring_bias=round(bias, 4), out_mark=round(om, 4),
                              out_edge=round(oe, 4), strike_len=round(slen, 3),
                              strike_bands=sbands, strike_all=sall,
                              score=round(score, 4), checked=score >= 0.5,
                              confidence=_score_confidence(score), rect=b["rect"],
                              method="diff" if has_diff else "fill"))
    _resolve_strikes(out)
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
        _detect_circled(rs)
        f = schema.get(fid)
        if f is None:
            continue

        if f.type == "flag":
            r = rs[0]
            result[fid] = dict(value=r.checked, confidence=r.confidence,
                               detail=[dict(opt=r.opt, fill=r.fill, halo=r.halo, mark=r.mark,
                                            ink=r.ink, score=r.score,
                                            checked=r.checked, circled=r.circled,
                                            struck=r.struck)])
            continue

        options = f.options or []
        if f.type == "choice":
            ranked = sorted(rs, key=lambda r: -r.score)
            top = ranked[0]
            second = ranked[1].score if len(ranked) > 1 else 0.0
            if not top.checked:
                value, conf = None, top.confidence
            else:
                value = options[top.opt] if top.opt < len(options) else str(top.opt)
                margin = top.score - second
                # 2位と差がないほど「どちらか判らない」＝確信度を落とす
                conf = min(top.confidence, round(min(1.0, 0.35 + margin * 0.65), 3))
            result[fid] = dict(value=value, confidence=conf,
                               detail=[dict(opt=r.opt, fill=r.fill, halo=r.halo, mark=r.mark,
                                            ink=r.ink, score=r.score,
                                            checked=r.checked, circled=r.circled,
                                            struck=r.struck)
                                       for r in rs])
            continue

        # multi: 各選択肢を独立に判定
        picked = [options[r.opt] if r.opt < len(options) else str(r.opt)
                  for r in rs if r.checked]
        conf = round(min((r.confidence for r in rs), default=0.0), 3)
        result[fid] = dict(value=picked, confidence=conf,
                           detail=[dict(opt=r.opt, fill=r.fill, halo=r.halo, mark=r.mark,
                                        ink=r.ink, score=r.score,
                                        checked=r.checked, circled=r.circled,
                                        struck=r.struck)
                                   for r in rs])
    return result
