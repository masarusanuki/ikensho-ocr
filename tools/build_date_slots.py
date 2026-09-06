# -*- coding: utf-8 -*-
"""日付欄を「年」「月」「日」で区切り、数字だけが入る小枠を作る。

区切り文字の位置は様式ごとに違うので、白紙様式を読み取って実測する。
各枠に1〜2桁の数字しか入らなくなるので、読み取りがぐっと安定する。
"""
import argparse
import json
import os
import sys

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MARKS = ("年", "月", "日")


def find_marks(blank, rect, pad=0.01):
    """白紙の日付欄で、印刷された区切り文字の位置を求める。

    白紙なので写っているのは「年」「月」「日」だけ（と下線）。
    OCR は小さな文字を取り逃すので、**縦方向のインクの塊**を数えて位置を出す。
    塊は左から順に 年・月・日 に対応する。
    """
    H, W = blank.shape
    x, y, w, h = rect
    px = w * pad
    x0 = max(0, int((x - px) * W))
    x1 = min(W, int((x + w + px) * W))
    y0 = max(0, int((y + h * 0.10) * H))
    y1 = min(H, int((y + h * 0.90) * H))
    roi = blank[y0:y1, x0:x1]
    if roi.size == 0 or roi.shape[1] < 20:
        return {}

    bw = cv2.adaptiveThreshold(roi, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                               cv2.THRESH_BINARY_INV, 25, 12)
    # 下線などの長い横線は区切り文字ではないので取り除く
    hk = cv2.getStructuringElement(cv2.MORPH_RECT, (max(12, roi.shape[1] // 4), 1))
    lines = cv2.dilate(cv2.morphologyEx(bw, cv2.MORPH_OPEN, hk), np.ones((3, 3), np.uint8))
    ink = cv2.bitwise_and(bw, cv2.bitwise_not(lines))

    cols = (ink > 0).sum(axis=0)
    thresh = max(1, int(roi.shape[0] * 0.10))
    on = cols >= thresh
    runs, start_i = [], None
    gap = max(2, int(roi.shape[0] * 0.12))
    blank_run = 0
    for i, v in enumerate(on):
        if v:
            if start_i is None:
                start_i = i
            blank_run = 0
        elif start_i is not None:
            blank_run += 1
            if blank_run >= gap:
                runs.append((start_i, i - blank_run))
                start_i, blank_run = None, 0
    if start_i is not None:
        runs.append((start_i, len(on) - 1))

    # 文字1つぶんの幅に近い塊だけ残す（文字高とほぼ同じ）
    ch = roi.shape[0]
    runs = [r for r in runs if ch * 0.45 <= (r[1] - r[0]) <= ch * 1.8]
    if not runs:
        return {}
    found = {}
    for mark, r in zip(MARKS, runs):
        found[mark] = (x0 + r[0], x0 + r[1])
    return found


def build_slots(blank, rect, marks):
    """区切り文字の間を小枠にする。"""
    H, W = blank.shape
    x, y, w, h = rect
    left = x * W
    slots = {}
    for key, mark in (("year", "年"), ("month", "月"), ("day", "日")):
        if mark not in marks:
            continue
        mx0, mx1 = marks[mark]
        pad = (mx1 - mx0) * 0.12
        s0, s1 = left + pad, mx0 - pad
        if s1 - s0 >= w * W * 0.05:
            slots[key] = [round(s0 / W, 6), round(y, 6), round((s1 - s0) / W, 6), round(h, 6)]
        left = mx1
    return slots


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*", help="対象の様式ID（既定: 全部）")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    tdir = os.path.join(ROOT, "templates")
    ids = args.ids or [f[:-5] for f in sorted(os.listdir(tdir)) if f.endswith(".json")]
    for tid in ids:
        path = os.path.join(tdir, f"{tid}.json")
        tpl = json.load(open(path, encoding="utf-8"))
        total = 0
        for page in tpl["pages"]:
            bpath = os.path.join(tdir, "blanks", page.get("blank") or page["ref"])
            blank = cv2.imread(bpath, cv2.IMREAD_GRAYSCALE)
            if blank is None:
                continue
            if blank.shape != (page["height"], page["width"]):
                blank = cv2.resize(blank, (page["width"], page["height"]),
                                   interpolation=cv2.INTER_CUBIC)
            for t in page["texts"]:
                if t.get("kind") != "date_wareki":
                    continue
                marks = find_marks(blank, t["rect"])
                slots = build_slots(blank, t["rect"], marks)
                got = "".join(k for k in MARKS if k in marks)
                if slots:
                    t["slots"] = slots
                    total += 1
                print(f"  {tid} p{page['index']} {t['field']:18s} "
                      f"区切り='{got}' 小枠={list(slots)}")
        if not args.dry_run:
            json.dump(tpl, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"{tid}: {total} 個の日付欄に小枠を設定"
              + ("（書き込みなし）" if args.dry_run else ""))


if __name__ == "__main__":
    main()
