# -*- coding: utf-8 -*-
"""様式テンプレート（物理座標）の読み込み。"""
import glob
import json
import os
from dataclasses import dataclass
from typing import Dict, List, Optional

import cv2
import numpy as np

# 様式テンプレートの置き場。環境変数 IKENSHO_TEMPLATES で差し替えられる。
DEFAULT_TEMPLATE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "templates")
TEMPLATE_DIR = os.environ.get("IKENSHO_TEMPLATES") or DEFAULT_TEMPLATE_DIR


@dataclass
class TemplatePage:
    index: int
    width: int
    height: int
    ref: str
    boxes: List[dict]
    texts: List[dict]
    blank: str = ""
    _ref_image: Optional[np.ndarray] = None
    _blank_image: Optional[np.ndarray] = None

    def ref_image(self, base_dir: str) -> Optional[np.ndarray]:
        if self._ref_image is None:
            path = os.path.join(base_dir, "refs", self.ref)
            if os.path.exists(path):
                self._ref_image = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
        return self._ref_image

    def blank_image(self, base_dir: str) -> Optional[np.ndarray]:
        """記入前の様式画像。読み取り時に差分をとってマークだけを抽出する。"""
        if self._blank_image is None:
            name = self.blank or self.ref
            path = os.path.join(base_dir, "blanks", name)
            if not os.path.exists(path):
                path = os.path.join(base_dir, "refs", name)
            if os.path.exists(path):
                img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
                if img is not None and (img.shape[1] != self.width or img.shape[0] != self.height):
                    img = cv2.resize(img, (self.width, self.height), interpolation=cv2.INTER_CUBIC)
                self._blank_image = img
        return self._blank_image


@dataclass
class Template:
    id: str
    name: str
    page_count: int
    pages: List[TemplatePage]
    base_dir: str

    def page(self, index: int) -> Optional[TemplatePage]:
        for p in self.pages:
            if p.index == index:
                return p
        return None


def load_templates(directory: Optional[str] = None) -> Dict[str, Template]:
    """様式テンプレートを読み込む。

    directory を省略すると、環境変数 IKENSHO_TEMPLATES か、
    リポジトリ内の templates/ を使う。別の場所に置いた独自の様式を
    読み込ませたい場合は、そのディレクトリを指定する。
    """
    directory = directory or TEMPLATE_DIR
    if not os.path.isdir(directory):
        raise FileNotFoundError(f"テンプレートの置き場が見つかりません: {directory}")
    out: Dict[str, Template] = {}
    for path in sorted(glob.glob(os.path.join(directory, "*.json"))):
        with open(path, encoding="utf-8") as fp:
            raw = json.load(fp)
        if "pages" not in raw:
            continue
        pages = [TemplatePage(index=p["index"], width=p["width"], height=p["height"],
                              ref=p["ref"], boxes=p["boxes"], texts=p["texts"],
                              blank=p.get("blank", ""))
                 for p in raw["pages"]]
        out[raw["id"]] = Template(id=raw["id"], name=raw["name"],
                                  page_count=raw.get("page_count", len(pages)),
                                  pages=pages, base_dir=directory)
    return out
