# -*- coding: utf-8 -*-
"""チェックボックスの記入判定。

印刷された枠線を除いた「内部のインク量」でチェックの有無を判定する。
OCR を使わないため、手書き・印刷・スキャンいずれでも安定して読める。
"""
from dataclasses import dataclass
from typing import Dict, List, Optional

import cv2
import numpy as np

# 内部インク率の判定しきい値
EMPTY_MAX = 0.10     # これ未満なら未チェック
FILLED_MIN = 0.28    # これ以上ならチェック済み


# 枠を丸で囲む記入への対応
HALO_MARGIN = 0.55       # 枠の外側どこまでを「丸」とみなすか（枠サイズ比）
HALO_EXCESS_MIN = 0.06   # 同一項目の他の選択肢より、これだけ濃ければ丸印とみなす

# 白紙様式との差分によるマーク検出
MARK_MARGIN = 0.45       # 枠の外側どこまでを見るか（枠サイズ比）。はみ出したレ点を拾う
MARK_EMPTY_MAX = 0.012   # 差分がこれ未満なら未記入
MARK_FILLED_MIN = 0.030  # 差分がこれ以上なら記入あり


@dataclass
class BoxReading:
    field: str
    opt: int
    fill: float           # 内部インク率 0..1
    halo: float           # 枠のすぐ外側のインク率 0..1（丸囲み検出用）
    mark: float           # 白紙様式との差分から得た記入量 0..1
    score: float          # 上記を統合した記入の強さ 0..1
    checked: bool
    confidence: float     # 0..1
    rect: List[float]
    circled: bool = False
    method: str = "fill"  # 判定に使った指標


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


def _mark_layer(warped: np.ndarray, blank: Optional[np.ndarray]) -> Optional[np.ndarray]:
    """白紙様式との差分をとり、手書きのマークだけを残した2値画像を作る。

    枠線・ラベル・説明文といった印刷内容が消えるため、
    枠からはみ出したレ点や枠を囲む丸印も素直に拾える。
    """
    if blank is None or blank.shape != warped.shape:
        return None
    scan = _binarize(warped)
    base = _binarize(blank)
    # 位置ずれの許容のため、白紙側のインクを少し太らせてから引く
    base = cv2.dilate(base, np.ones((3, 3), np.uint8), iterations=1)
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



def _unit(value: float, lo: float, hi: float) -> float:
    """lo で 0、hi で 1 になるように 0..1 へ写す。"""
    if hi <= lo:
        return 0.0
    return max(0.0, min(1.0, (value - lo) / (hi - lo)))


def _combined_score(fill: float, mark: float, has_diff: bool) -> float:
    """枠内インク率と差分マークの両方から、記入の強さを 0..1 で表す。

    枠の中に収まったチェックは fill が、枠からはみ出したレ点や
    枠を囲む丸印は mark が拾うので、大きい方を採用する。
    """
    s = _unit(fill, EMPTY_MAX, FILLED_MIN)
    if has_diff:
        s = max(s, _unit(mark, MARK_EMPTY_MAX, MARK_FILLED_MIN))
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
        mark = _mark_ratio(diff, x, y, w, h) if diff is not None else 0.0
        score = _combined_score(fill, mark, diff is not None)
        out.append(BoxReading(field=b["field"], opt=b["opt"], fill=round(fill, 4),
                              halo=round(halo, 4), mark=round(mark, 4),
                              score=round(score, 4), checked=score >= 0.5,
                              confidence=_score_confidence(score), rect=b["rect"],
                              method="diff" if diff is not None else "fill"))
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
                               detail=[dict(opt=r.opt, fill=r.fill, halo=r.halo, mark=r.mark, score=r.score,
                                            checked=r.checked, circled=r.circled)])
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
                               detail=[dict(opt=r.opt, fill=r.fill, halo=r.halo, mark=r.mark, score=r.score,
                                            checked=r.checked, circled=r.circled)
                                       for r in rs])
            continue

        # multi: 各選択肢を独立に判定
        picked = [options[r.opt] if r.opt < len(options) else str(r.opt)
                  for r in rs if r.checked]
        conf = round(min((r.confidence for r in rs), default=0.0), 3)
        result[fid] = dict(value=picked, confidence=conf,
                           detail=[dict(opt=r.opt, fill=r.fill, halo=r.halo, mark=r.mark, score=r.score,
                                        checked=r.checked, circled=r.circled)
                                   for r in rs])
    return result
