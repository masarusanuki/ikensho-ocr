# -*- coding: utf-8 -*-
"""様式テンプレート（物理座標）の読み込み。"""
import glob
import json
import os
from dataclasses import dataclass
from typing import Dict, List, Optional

import cv2
import numpy as np

TEMPLATE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "templates")


@dataclass
class TemplatePage:
    index: int
    width: int
    height: int
    ref: str
    boxes: List[dict]
    texts: List[dict]
    _ref_image: Optional[np.ndarray] = None

    def ref_image(self, base_dir: str) -> Optional[np.ndarray]:
        if self._ref_image is None:
            path = os.path.join(base_dir, "refs", self.ref)
            if os.path.exists(path):
                self._ref_image = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
        return self._ref_image


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


def load_templates(directory: str = TEMPLATE_DIR) -> Dict[str, Template]:
    out: Dict[str, Template] = {}
    for path in sorted(glob.glob(os.path.join(directory, "*.json"))):
        with open(path, encoding="utf-8") as fp:
            raw = json.load(fp)
        if "pages" not in raw:
            continue
        pages = [TemplatePage(index=p["index"], width=p["width"], height=p["height"],
                              ref=p["ref"], boxes=p["boxes"], texts=p["texts"])
                 for p in raw["pages"]]
        out[raw["id"]] = Template(id=raw["id"], name=raw["name"],
                                  page_count=raw.get("page_count", len(pages)),
                                  pages=pages, base_dir=directory)
    return out
