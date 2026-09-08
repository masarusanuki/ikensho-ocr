# -*- coding: utf-8 -*-
"""OCR の正解データを作るための「切り抜き一覧」画像を作る。

テキスト欄を1つずつ切り抜いて番号を振り、縦に並べた画像にする。
人（または多モーダルなモデル）がこれを見て、番号ごとの正解を書き取る。

    python3 tools/make_ocr_truth_sheet.py sample/A_type_綺麗.pdf --out /tmp/sheet
        → /tmp/sheet/A_type_綺麗_1.png … と、番号と項目の対応（標準出力・JSON）

正解は `bench/ocr_truth.json` に
    {"A_type_綺麗.pdf": {"clinic_name": "筑波記念病院", ...}, ...}
の形で置く。`tools/benchmark_ocr.py` がこれを使って各エンジンを測る。
"""
import argparse
import json
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "python"))

from ikensho_ocr import align, imaging, ocr as ocr_mod, textbox  # noqa: E402
from ikensho_ocr.schema import load_schema  # noqa: E402
from ikensho_ocr.templates import load_templates  # noqa: E402

ROW_H = 74            # 1行の高さ（切り抜きはこの高さに合わせる）
PAD = 8
LABEL_W = 74          # 左に番号を書く幅
SHEET_ROWS = 12       # 1枚に並べる行数


def crops_for(path, dpi=imaging.DEFAULT_DPI):
    """様式を判別して、テキスト欄の切り抜きを（項目, 画像）で返す。"""
    tpls = load_templates()
    schema = load_schema()
    by_id = {f.id: f for f in schema}
    out = []
    for sp in imaging.load_any(path, dpi):
        m = align.match_page(sp.image, tpls)
        if m is None:
            continue
        tpl = tpls[m.template_id]
        page = tpl.page(m.page_index)
        if page is None:
            continue
        blank = page.blank_image(tpl.base_dir)
        H, W = m.warped.shape[:2]
        for t in page.texts:
            f = by_id.get(t["field"])
            if f is None or f.is_date or f.type == "circle":
                continue
            rect = textbox.widen_left(blank, t["rect"])
            if not ocr_mod.has_ink(m.warped, rect):
                continue
            x, y, w, h = rect
            x0, y0 = max(0, int(x * W)), max(0, int(y * H))
            x1, y1 = min(W, int((x + w) * W)), min(H, int((y + h) * H))
            if x1 - x0 < 10 or y1 - y0 < 8:
                continue
            out.append((f, m.warped[y0:y1, x0:x1]))
    return out


def sheet(items, start_no):
    """切り抜きを縦に並べた1枚の画像を作る。"""
    rows = []
    for i, (_f, img) in enumerate(items):
        scale = ROW_H / max(img.shape[0], 1)
        # 幅が広すぎる欄（記述）は縮めて全体を見せる
        resized = cv2.resize(img, None, fx=scale, fy=scale,
                             interpolation=cv2.INTER_CUBIC)
        if resized.shape[1] > 1500:
            s2 = 1500 / resized.shape[1]
            resized = cv2.resize(resized, None, fx=s2, fy=s2,
                                 interpolation=cv2.INTER_AREA)
        rows.append(resized)
    width = LABEL_W + max(r.shape[1] for r in rows) + PAD * 2
    height = sum(r.shape[0] + PAD for r in rows) + PAD
    canvas = np.full((height, width), 255, np.uint8)
    y = PAD
    for i, r in enumerate(rows):
        canvas[y:y + r.shape[0], LABEL_W:LABEL_W + r.shape[1]] = r
        cv2.putText(canvas, f"{start_no + i}", (6, y + r.shape[0] // 2 + 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, 0, 2, cv2.LINE_AA)
        cv2.line(canvas, (0, y + r.shape[0] + PAD // 2),
                 (width, y + r.shape[0] + PAD // 2), 200, 1)
        y += r.shape[0] + PAD
    return canvas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--out", default="/tmp/ocr_truth_sheet")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    mapping = {}
    for path in args.files:
        base = os.path.basename(path)
        items = crops_for(path)
        print(f"== {base}  テキスト欄 {len(items)} 件")
        no = 1
        for part, i in enumerate(range(0, len(items), SHEET_ROWS), start=1):
            chunk = items[i:i + SHEET_ROWS]
            img = sheet(chunk, no)
            name = f"{os.path.splitext(base)[0]}_{part}.png"
            cv2.imwrite(os.path.join(args.out, name), img)
            print(f"   {name}")
            for j, (f, _img) in enumerate(chunk):
                mapping[f"{base}#{no + j}"] = dict(field=f.id, label=f.label)
                print(f"      {no + j:3d}  {f.id:28s} {f.label}")
            no += len(chunk)
    with open(os.path.join(args.out, "mapping.json"), "w", encoding="utf-8") as fh:
        json.dump(mapping, fh, ensure_ascii=False, indent=1)
    print(f"\n対応表: {os.path.join(args.out, 'mapping.json')}")


if __name__ == "__main__":
    main()
