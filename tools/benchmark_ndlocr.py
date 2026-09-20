# -*- coding: utf-8 -*-
"""NDLOCR-Lite を、いまの読み方と正解データで比べる。

3つのやり方を同じ欄・同じ正解で突き合わせる。

    いま        … PP-OCR に欄の切り抜きを渡す（本アプリの既定）
    NDL欄ごと   … NDLOCR に欄の切り抜きを渡す（中で行を見つけ直す）
    NDLページ   … NDLOCR でページを1枚まるごと読み、行を欄に振り分ける

    python3 tools/benchmark_ndlocr.py --limit 12
"""
import argparse
import collections
import difflib
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "python"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

from benchmark_seigo import (DATE_MAP, JOIN_MAP, TEXT_MAP, load_truth,  # noqa: E402
                             pdf_path)
from ikensho_ocr import align, imaging, ndlocr, ocr as ocr_mod, textbox  # noqa: E402
from ikensho_ocr.schema import load_schema                               # noqa: E402
from ikensho_ocr.templates import load_templates                         # noqa: E402


def norm(text):
    """比べる前に、空白のゆれを均す。

    生の読み取りには `4 年 6 月 7 日` のように空白が入る。本体では
    日付解析や辞書照合を通るので消えるが、ここでは生を比べているため
    **空白だけは均さないと不当に低く出る**（実際に出た）。
    """
    return "".join(str(text or "").split())


def ratio(want, got):
    want, got = norm(want), norm(got)
    if not want and not got:
        return 1.0
    return difflib.SequenceMatcher(None, want, got).ratio()


def expect_of(want, fid):
    """正解データから、その欄の期待値を組み立てる（benchmark_seigo と同じ規則）。"""
    if fid in DATE_MAP:
        pre = DATE_MAP[fid]
        parts = [("1" if (want.get(f"{pre}_{k}") or "").strip() in ("元", "元年")
                  else want.get(f"{pre}_{k}")) for k in ("年", "月", "日")]
        if not any(parts):
            return None
        return "".join(f"{v}{m}" for v, m in zip(parts, ("年", "月", "日")) if v)
    if fid in JOIN_MAP:
        a, b, sep = JOIN_MAP[fid]
        if not want.get(a) and not want.get(b):
            return None
        return sep.join(x for x in (want.get(a), want.get(b)) if x)
    key = next((k for k, v in TEXT_MAP.items() if v == fid), None)
    return want.get(key) if key else None


def run_one(doc, ways):
    """1通ぶんを、指定のやり方それぞれで読む。"""
    templates = load_templates()
    schema = load_schema()
    ppocr = ocr_mod.get_engine("auto") if "いま" in ways else None
    ndl = ndlocr.NdlOcr() if "NDL欄ごと" in ways else None
    got = {w: {} for w in ways}
    times = collections.Counter()
    for sp in imaging.load_any(pdf_path(doc), imaging.DEFAULT_DPI):
        m = align.match_page(sp.image, templates)
        if m is None:
            continue
        page = templates[m.template_id].page(m.page_index)
        if page is None:
            continue
        blank = page.blank_image(templates[m.template_id].base_dir)
        reader = None
        if "NDLページ" in ways or "NDL併用" in ways:
            t0 = time.time()
            reader = ndlocr.PageReader(m.warped)
            times["ページの検出"] += time.time() - t0
        for t in page.texts:
            f = schema.get(t["field"])
            if f is None or f.type == "circle":
                continue
            rect = textbox.widen_left(blank, t["rect"]) if blank is not None else t["rect"]
            multiline = f.type == "textarea"
            charset = t.get("charset") or f.charset or ""
            H, W = m.warped.shape[:2]
            x, y, w, h = rect
            roi = m.warped[int(y * H):int((y + h) * H), int(x * W):int((x + w) * W)]
            if "いま" in ways:
                t0 = time.time()
                got["いま"][f.id] = ppocr.read(
                    ocr_mod.prepare_roi(m.warped, rect,
                                        target_height=48), multiline, charset).text
                times["いま"] += time.time() - t0
            if "NDL欄ごと" in ways:
                t0 = time.time()
                got["NDL欄ごと"][f.id] = ndl.read(roi, multiline, charset).text
                times["NDL欄ごと"] += time.time() - t0
            if reader is not None:
                t0 = time.time()
                got["NDLページ"][f.id] = reader.text_in(
                    rect, multiline, charset).text
                times["NDLページ"] += time.time() - t0
            if "NDL併用" in ways:
                t0 = time.time()
                got["NDL併用"][f.id] = reader.text_in(
                    rect, multiline, charset, gray=m.warped).text
                times["NDL併用"] += time.time() - t0
    return doc, got, dict(times)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=8)
    ap.add_argument("--jobs", type=int, default=1)
    ap.add_argument("--detail", type=int, default=0)
    ap.add_argument("--ways", nargs="*",
                    default=["いま", "NDL欄ごと", "NDLページ"],
                    help="いま / NDL欄ごと / NDLページ / NDL併用")
    args = ap.parse_args()

    truth = load_truth()["text"]
    docs = sorted(truth)[:args.limit]
    print(f"{len(docs)} 通で比べます: {' / '.join(args.ways)}")

    results = {}
    times = collections.Counter()
    t0 = time.time()
    if args.jobs > 1:
        import functools
        import multiprocessing as mp
        with mp.Pool(args.jobs) as pool:
            fn = functools.partial(run_one, ways=args.ways)
            for i, (doc, got, tm) in enumerate(pool.imap_unordered(fn, docs), 1):
                results[doc] = got
                times.update(tm)
                print(f"  {i}/{len(docs)}（{time.time() - t0:.0f}秒）", flush=True)
    else:
        for i, doc in enumerate(docs, 1):
            _, got, tm = run_one(doc, args.ways)
            results[doc] = got
            times.update(tm)
            print(f"  {i}/{len(docs)}（{time.time() - t0:.0f}秒）", flush=True)

    # 集計
    score = {w: [0.0, 0, 0] for w in args.ways}      # 文字率の合計 / 件数 / 完全一致
    per_field = {w: collections.defaultdict(lambda: [0.0, 0]) for w in args.ways}
    misses = []
    for doc in docs:
        want = truth.get(doc) or {}
        for fid in set(TEXT_MAP.values()) | set(JOIN_MAP) | set(DATE_MAP):
            expect = expect_of(want, fid)
            if expect is None or not str(expect).strip():
                continue
            row = {}
            for w in args.ways:
                mine = (results.get(doc) or {}).get(w, {}).get(fid, "")
                r = ratio(expect, mine)
                score[w][0] += r
                score[w][1] += 1
                score[w][2] += int(norm(expect) == norm(mine))
                per_field[w][fid][0] += r
                per_field[w][fid][1] += 1
                row[w] = (r, mine)
            if len(misses) < args.detail and args.ways[0] in row:
                base = row[args.ways[0]][0]
                best = max(row.items(), key=lambda kv: kv[1][0])
                if best[1][0] - base > 0.25:
                    misses.append((doc, fid, expect, row))

    print(f"\n■ 全体（{score[args.ways[0]][1]} 件）")
    print(f"  {'やり方':12s} {'文字正解率':>9s} {'完全一致':>9s} {'所要':>9s}")
    for w in args.ways:
        tot, n, exact = score[w]
        t = times.get(w)
        ts = f"{t:.0f}秒" if t else "—"
        print(f"  {w:12s} {100 * tot / max(n, 1):8.2f}% {100 * exact / max(n, 1):8.2f}% {ts:>9s}")

    print("\n■ 欄ごと（いまとの差が大きい順）")
    base = args.ways[0]
    rows = []
    for fid, (tot, n) in per_field[base].items():
        cur = 100 * tot / max(n, 1)
        best_w, best_v = base, cur
        for w in args.ways[1:]:
            t2, n2 = per_field[w][fid]
            v = 100 * t2 / max(n2, 1)
            if v > best_v:
                best_w, best_v = w, v
        rows.append((best_v - cur, fid, cur, best_w, best_v, n))
    rows.sort(reverse=True)
    print(f"  {'欄':26s} {'いま':>7s} {'いちばん良い':>12s} {'差':>7s}  件数")
    for diff, fid, cur, bw, bv, n in rows[:16]:
        mark = f"{bw} {bv:.1f}%" if diff > 0.05 else "—"
        print(f"  {fid:26s} {cur:6.1f}% {mark:>14s} {diff:+6.1f}  {n}")

    if misses:
        print("\n■ いまが外していて、他が読めている例")
        for doc, fid, expect, row in misses:
            print(f"  {doc} {fid}")
            print(f"    正解      「{expect}」")
            for w, (r, mine) in row.items():
                print(f"    {w:10s}「{mine}」  {r:.2f}")
    print(f"\n所要 {time.time() - t0:.0f} 秒")


if __name__ == "__main__":
    main()
