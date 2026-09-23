# -*- coding: utf-8 -*-
"""入力ファイル（PDF・画像）をページ画像に変換する。

スマートフォンやタブレットのカメラ撮影にも対応するため、
用紙の輪郭を検出して台形補正するステップを持つ。
"""
import os
from dataclasses import dataclass
from typing import List, Optional

import cv2
import numpy as np

DEFAULT_DPI = 200
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp", ".heic"}


@dataclass
class SourcePage:
    """入力1ページ分の画像。"""
    image: np.ndarray          # グレースケール
    source: str                # 元ファイル名
    source_page: int           # 元ファイル内のページ番号(1始まり)
    from_pdf: bool
    dewarped: bool = False


def is_pdf(path: str) -> bool:
    return os.path.splitext(path)[1].lower() == ".pdf"


def load_pdf(path: str, dpi: int = DEFAULT_DPI) -> List[SourcePage]:
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(path)
    pages = []
    for i in range(len(doc)):
        arr = np.asarray(doc[i].render(scale=dpi / 72.0, grayscale=True).to_pil())
        pages.append(SourcePage(image=arr, source=os.path.basename(path),
                                source_page=i + 1, from_pdf=True))
    return pages


def _order_corners(pts: np.ndarray) -> np.ndarray:
    s = pts.sum(axis=1)
    d = np.diff(pts, axis=1).ravel()
    return np.array([pts[np.argmin(s)], pts[np.argmin(d)],
                     pts[np.argmax(s)], pts[np.argmax(d)]], dtype=np.float32)


def detect_paper(gray: np.ndarray, min_area_ratio: float = 0.35) -> Optional[np.ndarray]:
    """写真の中から用紙の四隅を検出する。見つからなければ None。"""
    h, w = gray.shape
    small = cv2.resize(gray, (min(w, 1000), int(h * min(w, 1000) / w)))
    sh, sw = small.shape
    blur = cv2.GaussianBlur(small, (5, 5), 0)
    edges = cv2.Canny(blur, 40, 120)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)
    cnts, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best, best_area = None, min_area_ratio * sw * sh
    for c in cnts:
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.02 * peri, True)
        if len(approx) != 4 or not cv2.isContourConvex(approx):
            continue
        area = abs(cv2.contourArea(approx))
        if area > best_area:
            best, best_area = approx, area
    if best is None:
        return None
    return _order_corners(best.reshape(4, 2).astype(np.float32)) * (w / sw)


def dewarp(gray: np.ndarray, corners: np.ndarray, dpi: int = DEFAULT_DPI) -> np.ndarray:
    """検出した四隅をA4比率の矩形に台形補正する。"""
    tl, tr, br, bl = corners
    wa = np.linalg.norm(br - bl)
    wb = np.linalg.norm(tr - tl)
    ha = np.linalg.norm(tr - br)
    hb = np.linalg.norm(tl - bl)
    width = max(wa, wb)
    height = max(ha, hb)
    # A4 の縦横比に寄せる（撮影角度による歪みを補正）
    a4 = 297.0 / 210.0
    if height / max(width, 1) < a4 * 0.8 or height / max(width, 1) > a4 * 1.2:
        height = width * a4
    out_w = int(round(width))
    out_h = int(round(height))
    dst = np.array([[0, 0], [out_w - 1, 0], [out_w - 1, out_h - 1], [0, out_h - 1]],
                   dtype=np.float32)
    M = cv2.getPerspectiveTransform(corners, dst)
    return cv2.warpPerspective(gray, M, (out_w, out_h), flags=cv2.INTER_CUBIC,
                               borderValue=255)


def normalize_photo(gray: np.ndarray) -> np.ndarray:
    """写真特有の照明ムラを平坦化する（スキャン画像でも無害）。"""
    bg = cv2.medianBlur(cv2.resize(gray, (gray.shape[1] // 8, gray.shape[0] // 8)), 21)
    bg = cv2.resize(bg, (gray.shape[1], gray.shape[0]), interpolation=cv2.INTER_LINEAR)
    bg = np.maximum(bg.astype(np.int16), 1)
    flat = np.clip(gray.astype(np.int16) * 220 // bg, 0, 255).astype(np.uint8)
    return flat


def load_image(path: str, camera: bool = True) -> List[SourcePage]:
    """画像ファイルを1ページとして読み込む。camera=True なら台形補正を試みる。"""
    data = np.fromfile(path, dtype=np.uint8)      # 日本語ファイル名対応
    img = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ValueError(f"画像を読み込めません: {path}")
    dewarped = False
    if camera:
        corners = detect_paper(img)
        if corners is not None:
            img = dewarp(img, corners)
            dewarped = True
        img = normalize_photo(img)
    return [SourcePage(image=img, source=os.path.basename(path), source_page=1,
                       from_pdf=False, dewarped=dewarped)]


def load_any(path: str, dpi: int = DEFAULT_DPI) -> List[SourcePage]:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        return load_pdf(path, dpi)
    if ext in IMAGE_EXT:
        return load_image(path)
    raise ValueError(f"対応していない形式です: {ext}")
