# -*- coding: utf-8 -*-
"""マスターPDFから公式様式テンプレート(templates/official_v1.json)を生成する。

チェックボックスの位置は PDF のテキストレイヤにある '□' 文字から取得し、
実際にレンダリングした画像上の輪郭にスナップして正確な矩形を得る。
"""
import json
import os
import sys
import unicodedata

import cv2
import numpy as np
import pdfplumber
import pypdfium2 as pdfium

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import form_definition as fd  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MASTER = os.path.join(ROOT, "master", "主医師意見書.pdf")
OUT_TEMPLATE = os.path.join(ROOT, "templates", "official_v1.json")
OUT_SCHEMA = os.path.join(ROOT, "schema", "ikensho.schema.json")
REF_DIR = os.path.join(ROOT, "templates", "refs")
BLANK_DIR = os.path.join(ROOT, "templates", "blanks")
DPI = 200


def norm(s):
    s = unicodedata.normalize("NFKC", s or "")
    return "".join(s.split()).replace("･", "・")


def extract_boxes(pdf_path):
    """PDF のテキストレイヤから □ の位置とラベルを文書順に取得。"""
    result = {}
    with pdfplumber.open(pdf_path) as pdf:
        for pi, page in enumerate(pdf.pages, 1):
            chars = sorted(page.chars, key=lambda c: (round(c["top"] / 4), c["x0"]))
            idxs = [i for i, c in enumerate(chars) if c["text"] == "□"]
            items = []
            for i in idxs:
                c = chars[i]
                label = ""
                for j in range(i + 1, min(i + 24, len(chars))):
                    d = chars[j]
                    if d["text"] == "□":
                        break
                    if abs(d["top"] - c["top"]) > 4:
                        break
                    if d["x0"] - chars[j - 1]["x1"] > 12:
                        break
                    label += d["text"]
                items.append(dict(x0=c["x0"], top=c["top"], x1=c["x1"], bottom=c["bottom"],
                                  label=label.strip()))
            result[pi] = dict(items=items, width=float(page.width), height=float(page.height))
    return result


def render(pdf_path, dpi=DPI):
    doc = pdfium.PdfDocument(pdf_path)
    pages = []
    for i in range(len(doc)):
        page = doc[i]
        bmp = page.render(scale=dpi / 72.0, grayscale=True)
        pages.append(np.asarray(bmp.to_pil()))
    return pages


def snap_to_contour(gray, cx, cy, expect_px):
    """期待位置周辺で実際の四角い輪郭を探し、正確な矩形を返す。"""
    pad = int(expect_px * 1.1)
    x0, y0 = max(0, int(cx - pad)), max(0, int(cy - pad))
    x1, y1 = min(gray.shape[1], int(cx + pad)), min(gray.shape[0], int(cy + pad))
    win = gray[y0:y1, x0:x1]
    if win.size == 0:
        return None
    bw = cv2.adaptiveThreshold(win, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                               cv2.THRESH_BINARY_INV, 25, 15)
    cnts, _ = cv2.findContours(bw, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    best, best_d = None, 1e9
    lo, hi = expect_px * 0.45, expect_px * 1.25
    for c in cnts:
        x, y, w, h = cv2.boundingRect(c)
        if not (lo <= w <= hi and lo <= h <= hi):
            continue
        if not (0.7 <= w / h <= 1.45):
            continue
        ccx, ccy = x0 + x + w / 2.0, y0 + y + h / 2.0
        d = (ccx - cx) ** 2 + (ccy - cy) ** 2
        if d < best_d:
            best_d, best = d, (x0 + x, y0 + y, w, h)
    if best is None or best_d > (expect_px * 0.8) ** 2:
        return None
    return best


def date_slots(pdf_path, page_index, rect, page_w, page_h):
    """日付欄を「年」「月」「日」で区切り、数字だけが入る小枠を作る。

    様式に印刷された区切り文字の位置は決まっているので、
    そこで割れば各枠には数字しか入らない。1〜2桁の数字だけを
    読めばよくなるので、OCR がぐっと楽になる。
    """
    import pdfplumber
    x, y, w, h = rect
    px0, py0, px1, py1 = x * page_w, y * page_h, (x + w) * page_w, (y + h) * page_h
    with pdfplumber.open(pdf_path) as pdf:
        chars = pdf.pages[page_index - 1].chars
    marks = {}
    for c in chars:
        if c["text"] not in "年月日":
            continue
        if not (px0 - 2 <= c["x0"] and c["x1"] <= px1 + 2):
            continue
        if not (py0 - 4 <= c["top"] and c["bottom"] <= py1 + 4):
            continue
        marks.setdefault(c["text"], (c["x0"], c["x1"]))

    slots = {}
    left = px0
    for key, mark in (("year", "年"), ("month", "月"), ("day", "日")):
        if mark not in marks:
            continue
        mx0, mx1 = marks[mark]
        pad = (mx1 - mx0) * 0.12
        s0, s1 = left + pad, mx0 - pad
        if s1 - s0 >= (px1 - px0) * 0.03:
            slots[key] = [round(s0 / page_w, 6), round(y, 6),
                          round((s1 - s0) / page_w, 6), round(h, 6)]
        left = mx1
    return slots


def main():
    boxes = extract_boxes(MASTER)
    images = render(MASTER)
    scale = DPI / 72.0
    fields = fd.field_map()

    os.makedirs(os.path.dirname(OUT_TEMPLATE), exist_ok=True)
    os.makedirs(os.path.dirname(OUT_SCHEMA), exist_ok=True)
    os.makedirs(REF_DIR, exist_ok=True)

    pages_out = []
    problems = []
    snapped = fallback = 0

    for pi in sorted(boxes):
        meta = boxes[pi]
        items = meta["items"]
        order = fd.BOX_ORDER[pi]
        if len(items) != len(order):
            problems.append(f"page{pi}: box count {len(items)} != order {len(order)}")
        gray = images[pi - 1]
        H, W = gray.shape
        page_boxes = []
        for (item, (field_id, opt_idx)) in zip(items, order):
            f = fields[field_id]
            if f["type"] in ("choice", "multi"):
                expected = f["options"][opt_idx]
            else:
                expected = f.get("match") or f["label"]
            got = norm(item["label"])
            exp = norm(expected)
            if exp and got and not (got.startswith(exp) or exp.startswith(got[:len(exp)])):
                problems.append(f"page{pi} '{field_id}[{opt_idx}]' expect '{expected}' got '{item['label'][:24]}'")

            # 期待矩形（PDF点→ピクセル）。□ グリフは em ボックスより一回り小さい。
            cx = (item["x0"] + item["x1"]) / 2.0 * scale
            cy = (item["top"] + item["bottom"]) / 2.0 * scale
            em_px = (item["x1"] - item["x0"]) * scale
            expect_px = em_px * 0.78
            snap = snap_to_contour(gray, cx, cy, expect_px)
            if snap:
                bx, by, bw_, bh_ = snap
                snapped += 1
            else:
                bx, by = cx - expect_px / 2, cy - expect_px / 2
                bw_ = bh_ = expect_px
                fallback += 1
            page_boxes.append(dict(
                field=field_id, opt=opt_idx,
                rect=[round(bx / W, 6), round(by / H, 6),
                      round(bw_ / W, 6), round(bh_ / H, 6)],
            ))

        page_texts = []
        for _, _, f in fd.all_fields():
            if f["type"] in ("text", "textarea", "circle") and f.get("page") == pi and f.get("rect"):
                x0, y0, x1, y1 = f["rect"]
                page_texts.append(dict(
                    field=f["id"], type=f["type"],
                    rect=[round(x0 / meta["width"], 6), round(y0 / meta["height"], 6),
                          round((x1 - x0) / meta["width"], 6),
                          round((y1 - y0) / meta["height"], 6)],
                    options=f.get("options"),
                    charset=f.get("charset", ""),
                    pii=f.get("pii", ""), kind=f.get("kind", ""),
                    era_field=f.get("era_field", ""),
                    default_era=f.get("default_era", ""),
                    always_pick=bool(f.get("always_pick")),
                ))
                if f.get("kind") == "date_wareki":
                    page_texts[-1]["slots"] = date_slots(
                        MASTER, pi, page_texts[-1]["rect"], meta["width"], meta["height"])

        ref_name = f"official_v1_p{pi}.png"
        cv2.imwrite(os.path.join(REF_DIR, ref_name),
                    cv2.resize(gray, (int(W * 0.5), int(H * 0.5)), interpolation=cv2.INTER_AREA))
        # 差分によるマーク抽出に使う白紙様式（テンプレート座標系と同じ解像度）
        os.makedirs(BLANK_DIR, exist_ok=True)
        cv2.imwrite(os.path.join(BLANK_DIR, ref_name), gray)
        pages_out.append(dict(index=pi, width=W, height=H, ref=ref_name,
                              blank=ref_name, boxes=page_boxes, texts=page_texts))

    template = dict(
        id="official_v1",
        name="主治医意見書（厚生労働省 標準様式）",
        schema_version="1.0.0",
        page_count=len(pages_out),
        aspect=round(images[0].shape[1] / images[0].shape[0], 6),
        pages=pages_out,
    )
    with open(OUT_TEMPLATE, "w", encoding="utf-8") as fp:
        json.dump(template, fp, ensure_ascii=False, indent=1)

    schema = dict(
        version="1.0.0",
        form_name="主治医意見書",
        sections=[dict(id=sid, title=stitle,
                       fields=[{k: v for k, v in f.items() if k != "rect"} for f in flds])
                  for sid, stitle, flds in fd.SECTIONS],
    )
    with open(OUT_SCHEMA, "w", encoding="utf-8") as fp:
        json.dump(schema, fp, ensure_ascii=False, indent=1)

    total = snapped + fallback
    print(f"チェックボックス {total} 個 / 輪郭スナップ成功 {snapped} ({snapped/total*100:.1f}%) / 推定 {fallback}")
    print(f"テキスト欄 {sum(len(p['texts']) for p in pages_out)} 個")
    print(f"問題: {len(problems)}")
    for p in problems[:30]:
        print("  -", p)


if __name__ == "__main__":
    main()
