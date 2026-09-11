# -*- coding: utf-8 -*-
"""ページ画像をテンプレート座標系に位置合わせし、様式とページ番号を判定する。"""
import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from .templates import Template, TemplatePage

# 管理画面のしきい値と対応させるため、環境変数で上書きできるようにする
MIN_INLIERS = int(os.environ.get("IKENSHO_MIN_INLIERS", "25"))
MIN_INLIER_RATIO = float(os.environ.get("IKENSHO_MIN_INLIER_RATIO", "0.30"))
# これ以上の倍率で引き伸ばすときは Lanczos を使う（それ未満は Cubic）。
# 実測で決める。2.0 にすると 100dpi の入力で悪化した（Lanczos の粒立ちが害）
LANCZOS_FROM = float(os.environ.get("IKENSHO_LANCZOS_FROM", "2.5"))


@dataclass
class PageMatch:
    """1ページの照合結果。"""
    template_id: str
    page_index: int
    warped: np.ndarray
    homography: np.ndarray
    inliers: int
    matches: int

    @property
    def score(self) -> float:
        """0..1 の照合スコア。インライア数と比率の両方を反映する。"""
        if self.matches == 0:
            return 0.0
        ratio = self.inliers / self.matches
        volume = min(self.inliers / 120.0, 1.0)
        return round(ratio * 0.6 + volume * 0.4, 4)


def _prep(gray: np.ndarray) -> np.ndarray:
    g = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)
    return cv2.GaussianBlur(g, (3, 3), 0)


def _register(src: np.ndarray, ref: np.ndarray,
              nfeatures: int = 4000) -> Tuple[Optional[np.ndarray], int, int]:
    orb = cv2.ORB_create(nfeatures, scaleFactor=1.2, nlevels=8, fastThreshold=8)
    k1, d1 = orb.detectAndCompute(_prep(src), None)
    k2, d2 = orb.detectAndCompute(_prep(ref), None)
    if d1 is None or d2 is None or len(k1) < 12 or len(k2) < 12:
        return None, 0, 0
    bf = cv2.BFMatcher(cv2.NORM_HAMMING)
    pairs = bf.knnMatch(d1, d2, k=2)
    # 対応候補が1つしか返らない組があるので、組ごとに長さを確かめる
    good = [p[0] for p in pairs
            if len(p) == 2 and p[0].distance < 0.75 * p[1].distance]
    if len(good) < 12:
        return None, len(good), 0
    sp = np.float32([k1[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    dp = np.float32([k2[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
    H, mask = cv2.findHomography(sp, dp, cv2.RANSAC, 4.0)
    if H is None or mask is None:
        return None, len(good), 0
    return H, len(good), int(mask.sum())


def _warp_interp(gray: np.ndarray, page) -> int:
    """テンプレートの大きさに合わせるときの、画素の埋め方を選ぶ。

    **ここが解像度の低い入力の要。** 入力が template より小さいと、
    ここで引き伸ばされる。線形（INTER_LINEAR）だとにじんで細い線が消え、
    あとの OCR でいくら拡大しても戻らない。

      入力が小さい（＝低解像度）… Cubic。2倍を超えるなら Lanczos
      入力が大きい             … Area。線形だと縮小で網目が出る
    """
    if os.environ.get("IKENSHO_WARP") == "linear":
        return cv2.INTER_LINEAR          # 以前の動き（効果を測るため）
    src = max(gray.shape[1], 1)
    ratio = page.width / src
    if ratio >= LANCZOS_FROM:
        return cv2.INTER_LANCZOS4
    if ratio > 1.02:
        return cv2.INTER_CUBIC
    if ratio < 0.98:
        return cv2.INTER_AREA
    return cv2.INTER_LINEAR


def match_page(gray: np.ndarray, templates: Dict[str, Template],
               restrict_to: Optional[str] = None) -> Optional[PageMatch]:
    """1枚のページ画像がどの様式の何ページ目かを判定し、位置合わせして返す。

    カメラ撮影のように1枚ずつ入る場合でも、ページ番号を自動判別できる。
    """
    best: Optional[PageMatch] = None
    for tid, tpl in templates.items():
        if restrict_to and tid != restrict_to:
            continue
        for tp in tpl.pages:
            ref = tp.ref_image(tpl.base_dir)
            if ref is None:
                continue
            # 参照画像は縮小保存しているのでテンプレート座標系へ拡大する
            scale = tp.width / ref.shape[1]
            H, nmatch, ninl = _register(gray, ref)
            if H is None or ninl < MIN_INLIERS:
                continue
            if ninl / max(nmatch, 1) < MIN_INLIER_RATIO:
                continue
            S = np.array([[scale, 0, 0], [0, scale, 0], [0, 0, 1]], dtype=np.float64)
            Hf = S @ H
            warped = cv2.warpPerspective(gray, Hf, (tp.width, tp.height),
                                         flags=_warp_interp(gray, tp),
                                         borderValue=255)
            cand = PageMatch(template_id=tid, page_index=tp.index, warped=warped,
                             homography=Hf, inliers=ninl, matches=nmatch)
            if best is None or cand.score > best.score:
                best = cand
    return best


def assign_pages(matches: List[Optional[PageMatch]]) -> List[Optional[PageMatch]]:
    """複数ページの照合結果を突き合わせ、様式を多数決で揃える。

    1ページずつ撮影された場合でも、同じ様式に属するページとして扱えるようにする。
    """
    votes: Dict[str, float] = {}
    for m in matches:
        if m:
            votes[m.template_id] = votes.get(m.template_id, 0) + m.score
    if not votes:
        return matches
    winner = max(votes, key=votes.get)
    return [m if (m is None or m.template_id == winner) else None for m in matches]
