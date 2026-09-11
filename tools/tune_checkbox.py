# -*- coding: utf-8 -*-
"""チェック判定の特徴量を正解データ100通ぶん書き出し、判定の規則を調整する。

読み取りのたびに100通を回すと時間がかかるので、
**特徴量だけ先に書き出して**、しきい値や規則はそれを使って試す。

    python3 tools/tune_checkbox.py dump --jobs 6      # 特徴量を書き出す
    python3 tools/tune_checkbox.py eval               # いまの規則で測る
    python3 tools/tune_checkbox.py search             # しきい値を探す
"""
import argparse
import csv
import json
import os
import sys
import time
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "python"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

FEATURES = os.path.join(ROOT, "bench", "seigo_features.json")
TRUTH_DIR = os.path.join(ROOT, "seigo", "extracted")


def _truth():
    checkbox = {}
    with open(os.path.join(TRUTH_DIR, "ground_truth_checkbox.csv"),
              encoding="utf-8-sig") as fh:
        reader = csv.reader(fh)
        header = next(reader)
        ids = [h.split(":")[0] for h in header[1:]]
        for row in reader:
            checkbox[row[0]] = {i: int(v) for i, v in zip(ids, row[1:])}
    marks = defaultdict(dict)
    with open(os.path.join(TRUTH_DIR, "ground_truth_marks.csv"),
              encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            marks[r["文書"]][r["ID"]] = r["印の種類"]
    return checkbox, marks


def features_for(doc):
    """1通ぶんの特徴量を集める。"""
    import numpy as np
    import cv2
    from ikensho_ocr import align, checkbox as cb, imaging
    from ikensho_ocr.templates import load_templates
    from benchmark_seigo import box_ids, pdf_path

    path = pdf_path(doc)
    if not path:
        return doc, {}
    templates = load_templates()
    mapping = box_ids(templates)
    out = {}
    for sp in imaging.load_any(path, imaging.DEFAULT_DPI):
        m = align.match_page(sp.image, templates)
        if m is None:
            continue
        tpl = templates[m.template_id]
        page = tpl.page(m.page_index)
        if page is None:
            continue
        blank = page.blank_image(tpl.base_dir)
        warped = m.warped
        bw = cb._binarize(warped)
        _blank_bw = cb._binarize(blank) if blank is not None else np.zeros_like(bw)
        diff = cb._mark_layer(warped, blank)
        H, W = warped.shape[:2]
        for b in page.boxes:
            key = mapping.get((m.page_index, b["field"], b["opt"]))
            if not key:
                continue
            x, y, w, h = b["rect"]
            x0, y0 = int(round(x * W)), int(round(y * H))
            bw_ = max(2, int(round(w * W)))
            bh_ = max(2, int(round(h * H)))
            f = dict(field=b["field"], opt=b["opt"], page=m.page_index)
            f["fill"] = cb._fill_ratio(bw, x0, y0, bw_, bh_)
            f["halo"] = cb._halo_ratio(bw, x0, y0, bw_, bh_)
            if diff is not None:
                f["mark"] = cb._mark_ratio(diff, x0, y0, bw_, bh_)
                # 枠の内側だけの書き込み量（隣の字を拾わない）
                inner = diff[max(0, y0):min(H, y0 + bh_), max(0, x0):min(W, x0 + bw_)]
                f["mark_in"] = float((inner > 0).mean()) if inner.size else 0.0
                # 枠の中心寄りだけ（枠線のにじみも避ける）
                ix = max(1, int(bw_ * 0.2)); iy = max(1, int(bh_ * 0.2))
                core = diff[max(0, y0 + iy):min(H, y0 + bh_ - iy),
                            max(0, x0 + ix):min(W, x0 + bw_ - ix)]
                f["mark_core"] = float((core > 0).mean()) if core.size else 0.0
                # 外側の輪（丸囲み／はみ出し用）。内側を除いた部分
                mx, my = int(round(bw_ * 0.45)), int(round(bh_ * 0.45))
                rx0, ry0 = max(0, x0 - mx), max(0, y0 - my)
                rx1, ry1 = min(W, x0 + bw_ + mx), min(H, y0 + bh_ + my)
                win = diff[ry0:ry1, rx0:rx1]
                if win.size:
                    total = float((win > 0).sum())
                    inner_sum = float((inner > 0).sum()) if inner.size else 0.0
                    ring_area = max(1, win.size - (inner.size if inner.size else 0))
                    f["mark_ring"] = (total - inner_sum) / ring_area
                    # 輪のどちら側に寄っているか（隣の字は片側に偏る）
                    cx = x0 + bw_ / 2 - rx0
                    left = float((win[:, :max(1, int(cx))] > 0).sum())
                    right = total - left
                    f["ring_bias"] = abs(left - right) / max(total, 1.0)
                else:
                    f["mark_ring"] = 0.0
                    f["ring_bias"] = 0.0
                # 枠の右下にずれて書かれた印（枠外はみ出し）を拾うための窓
                qx0, qy0 = max(0, x0 + int(bw_ * 0.35)), max(0, y0 - int(bh_ * 0.1))
                qx1, qy1 = min(W, x0 + int(bw_ * 1.6)), min(H, y0 + int(bh_ * 1.4))
                q = diff[qy0:qy1, qx0:qx1]
                f["mark_rd"] = float((q > 0).mean()) if q.size else 0.0
                # 枠の中と外がつながっているか（隣の手書きは枠に触れない）
                tx0, tx1 = max(0, x0 + int(bw_ * 0.6)), min(W, x0 + bw_)
                t = diff[max(0, y0):min(H, y0 + bh_), tx0:tx1]
                f["mark_redge"] = float((t > 0).mean()) if t.size else 0.0
                # 二重線で消した印を見つけるための手がかり:
                # 枠を横切る長い横線が、枠の左右に突き抜けているか
                sx0, sx1 = max(0, x0 - bw_), min(W, x0 + bw_ * 2)
                strip = diff[max(0, y0):min(H, y0 + bh_), sx0:sx1]
                if strip.size:
                    rows = (strip > 0).sum(axis=1)
                    full = float(strip.shape[1])
                    # 横に長く伸びている行の数（枠幅の1.6倍以上）
                    f["long_rows"] = int((rows >= bw_ * 1.6).sum())
                    f["max_row"] = float(rows.max() / max(full, 1))
                    # 左右にはみ出しているか
                    lcol = (strip[:, :max(1, bw_ // 2)] > 0).sum()
                    rcol = (strip[:, -max(1, bw_ // 2):] > 0).sum()
                    f["cross_lr"] = float(min(lcol, rcol) / max(bh_, 1))
                else:
                    f["long_rows"] = 0
                    f["max_row"] = 0.0
                    f["cross_lr"] = 0.0
                # 二重線は「枠を横切る細長いかたまり」。
                # 枠の中に収まる印（■ や レ）は、幅が枠幅を超えない。
                ex, ey = int(bw_ * 1.2), int(bh_ * 0.8)
                cx0, cy0 = max(0, x0 - ex), max(0, y0 - ey)
                cx1, cy1 = min(W, x0 + bw_ + ex), min(H, y0 + bh_ + ey)
                area = diff[cy0:cy1, cx0:cx1]
                widest = 0.0
                widest_ratio = 0.0
                n_wide = 0
                if area.size:
                    num, lab, stats, _ = cv2.connectedComponentsWithStats(
                        (area > 0).astype(np.uint8), 8)
                    bx0, by0 = x0 - cx0, y0 - cy0
                    for i in range(1, num):
                        cx, cy, cw, ch, ar = stats[i]
                        if ar < 8:
                            continue
                        # 枠の中身に掛かっているものだけを見る
                        if cx > bx0 + bw_ or cx + cw < bx0 or cy > by0 + bh_ \
                                or cy + ch < by0:
                            continue
                        rel = cw / max(bw_, 1)
                        if rel > widest:
                            widest = rel
                            widest_ratio = cw / max(ch, 1)
                        if rel >= 1.4 and cw / max(ch, 1) >= 2.2:
                            n_wide += 1
                f["comp_w"] = float(widest)
                f["comp_ratio"] = float(widest_ratio)
                f["n_wide"] = int(n_wide)

                # 二重線は差分では途切れる（印刷の枠線や文字と重なった部分が
                # 消えるため）。元画像から「長い横線」だけを取り出し、
                # 白紙様式にも同じ線があるもの（罫線）を除く。
                by0, by1 = max(0, y0 - bh_), min(H, y0 + bh_ * 2)
                bx0, bx1 = max(0, x0 - int(bw_ * 1.8)), min(W, x0 + int(bw_ * 2.8))
                band = bw[by0:by1, bx0:bx1]
                bband = _blank_bw[by0:by1, bx0:bx1]
                if band.size:
                    ker = cv2.getStructuringElement(
                        cv2.MORPH_RECT, (max(6, int(bw_ * 1.3)), 1))
                    lines = cv2.morphologyEx(band, cv2.MORPH_OPEN, ker)
                    # 白紙様式の罫線は、重ね合わせのずれで数ピクセル上下する。
                    # 縦に厚く膨らませて確実に消す（残ると「手書きの横線」に見える）
                    plines = cv2.dilate(
                        cv2.morphologyEx(bband, cv2.MORPH_OPEN, ker),
                        np.ones((9, 5), np.uint8))
                    written = cv2.bitwise_and(lines, cv2.bitwise_not(plines))
                    # 枠の中を通る行だけを見る（枠の下の罫線を拾わないため）
                    ry0 = max(0, y0 - by0 + int(bh_ * 0.12))
                    ry1 = min(written.shape[0], y0 - by0 + bh_ - int(bh_ * 0.12))
                    rows_ = (written[ry0:ry1] > 0).sum(axis=1)
                    f["hline_len"] = float(rows_.max() / max(bw_, 1)) if rows_.size else 0.0
                    # 何本あるか（二重線なら2本）
                    on = rows_ >= bw_ * 1.2 if rows_.size else []
                    bands_ = 0
                    prev = False
                    for v in on:
                        if v and not prev:
                            bands_ += 1
                        prev = bool(v)
                    f["hline_bands"] = int(bands_)
                    # 枠の左右どちらにも突き抜けている行だけを見る
                    MG = 0.3
                    lx = max(1, x0 - bx0 - int(bw_ * MG))
                    rx = min(written.shape[1] - 1,
                             x0 - bx0 + bw_ + int(bw_ * MG))
                    seg = written[ry0:ry1]
                    okrow = ((seg[:, :lx] > 0).any(axis=1)
                             & (seg[:, rx:] > 0).any(axis=1))
                    r2 = np.where(okrow, rows_, 0)
                    f["hl2_len"] = float(r2.max() / max(bw_, 1)) if r2.size else 0.0
                    b2 = 0
                    prev = False
                    for v in (r2 >= bw_ * 1.2) if r2.size else []:
                        if v and not prev:
                            b2 += 1
                        prev = bool(v)
                    f["hl2_bands"] = int(b2)
                else:
                    f["hline_len"] = 0.0
                    f["hline_bands"] = 0
                    f["hl2_len"] = 0.0
                    f["hl2_bands"] = 0
            out[key] = {k: (round(v, 4) if isinstance(v, float) else v)
                        for k, v in f.items()}
        bw.delete() if hasattr(bw, "delete") else None
    return doc, out


def cmd_dump(args):
    checkbox, _ = _truth()
    docs = sorted(checkbox)
    if args.limit:
        docs = docs[:args.limit]
    t0 = time.time()
    data = {}
    if args.jobs > 1:
        import multiprocessing as mp
        with mp.Pool(args.jobs) as pool:
            for i, (doc, f) in enumerate(pool.imap_unordered(features_for, docs), 1):
                data[doc] = f
                if i % 20 == 0:
                    print(f"  {i}/{len(docs)}（{time.time() - t0:.0f}秒）")
    else:
        for i, doc in enumerate(docs, 1):
            data[doc] = features_for(doc)[1]
            if i % 20 == 0:
                print(f"  {i}/{len(docs)}（{time.time() - t0:.0f}秒）")
    os.makedirs(os.path.dirname(FEATURES), exist_ok=True)
    with open(FEATURES, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False)
    n = sum(len(v) for v in data.values())
    print(f"{len(data)} 通 / {n:,} 枠ぶんの特徴量を書き出しました: {FEATURES}"
          f"（{time.time() - t0:.0f}秒）")


def load_features():
    with open(FEATURES, encoding="utf-8") as fh:
        return json.load(fh)


def evaluate(decide, name=""):
    """decide(f) -> bool を、正解と突き合わせる。"""
    checkbox, marks = _truth()
    data = load_features()
    tp = fp = fn = tn = 0
    struck_ok = struck_ng = 0
    by_kind = defaultdict(lambda: [0, 0])
    for doc, boxes in data.items():
        want = checkbox.get(doc) or {}
        mk = marks.get(doc) or {}
        for bid, expect in want.items():
            f = boxes.get(bid)
            if f is None:
                continue
            pred = 1 if decide(f) else 0
            kind = mk.get(bid)
            if expect and pred:
                tp += 1
            elif expect and not pred:
                fn += 1
            elif not expect and pred:
                fp += 1
                if kind:
                    struck_ng += 1
            else:
                tn += 1
                if kind:
                    struck_ok += 1
            if kind:
                by_kind[kind][0] += int(pred == expect)
                by_kind[kind][1] += 1
    total = tp + fp + fn + tn
    acc = (tp + tn) / max(total, 1)
    print(f"{name:28s} 正解率 {100 * acc:6.2f}%  見落とし {fn:4d}  "
          f"誤検出 {fp - struck_ng:4d}  訂正の誤り {struck_ng:3d}")
    return dict(acc=acc, fn=fn, fp=fp - struck_ng, struck_ng=struck_ng,
                by_kind={k: v for k, v in by_kind.items()}, total=total)


def current_rule(f):
    """いまの実装と同じ判定。"""
    from ikensho_ocr import checkbox as cb
    score = cb._combined_score(f["fill"], f.get("mark", 0.0), "mark" in f)
    return score >= 0.5


def cmd_eval(args):
    r = evaluate(current_rule, "いまの規則")
    print("\n印の種類ごと:")
    for kind, (ok, n) in sorted(r["by_kind"].items(), key=lambda kv: kv[1][0] / max(kv[1][1], 1)):
        print(f"  {kind:16s} {100 * ok / max(n, 1):6.2f}%  ({ok}/{n})")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("dump")
    d.add_argument("--jobs", type=int, default=1)
    d.add_argument("--limit", type=int, default=0)
    d.set_defaults(func=cmd_dump)
    e = sub.add_parser("eval")
    e.set_defaults(func=cmd_eval)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
