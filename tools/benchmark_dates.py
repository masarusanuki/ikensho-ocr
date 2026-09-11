# -*- coding: utf-8 -*-
"""日付欄だけを正解データと突き合わせる。年・月・日を別々に数える。

日付は「年と月は取れるのに日だけ抜ける」という外し方をするので、
まとめた正解率では気付けない。**部分ごとに**測る。

    python3 tools/benchmark_dates.py --limit 20 --jobs 6
    python3 tools/benchmark_dates.py --detail 20        # 外した箇所を並べる
"""
import argparse
import collections
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "python"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

from benchmark_seigo import DATE_MAP, load_truth, pdf_path      # noqa: E402
from ikensho_ocr import align, extract, imaging                 # noqa: E402
from ikensho_ocr.schema import load_schema                       # noqa: E402
from ikensho_ocr.templates import load_templates                 # noqa: E402

PARTS = ("year", "month", "day")
JA = {"year": "年", "month": "月", "day": "日"}


def norm_truth(value: str) -> str:
    """正解の表記を数字にそろえる。元年は「元」と書かれている。"""
    v = (value or "").strip()
    return "1" if v in ("元", "元年") else v


DPI = int(os.environ.get("IKENSHO_BENCH_DPI", str(imaging.DEFAULT_DPI)))


def run_one(doc):
    """1通ぶんの日付欄を読む。{項目: {year/month/day: 値}} を返す。"""
    templates = load_templates()
    schema = load_schema()
    out = {}
    # 低い dpi で読み込むと、解像度の低い入力を模擬できる
    for sp in imaging.load_any(pdf_path(doc), DPI):
        m = align.match_page(sp.image, templates)
        if m is None:
            continue
        page = templates[m.template_id].page(m.page_index)
        if page is None:
            continue
        for t in page.texts:
            f = schema.get(t["field"])
            if f is None or not f.is_date or t["field"] not in DATE_MAP:
                continue
            entry = extract._read_date_slots(m.warped, t)
            out[t["field"]] = dict((entry.get("date") or {}), raw=entry.get("raw", ""))
    return doc, out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--jobs", type=int, default=1)
    ap.add_argument("--detail", type=int, default=0, help="外した箇所を並べる件数")
    args = ap.parse_args()

    text_truth = load_truth()["text"]
    docs = sorted(text_truth)
    if args.limit:
        docs = docs[:args.limit]
    print(f"{len(docs)} 通の日付欄を測ります（読み込み {DPI} dpi）")

    t0 = time.time()
    got = {}
    if args.jobs > 1:
        import multiprocessing as mp
        with mp.Pool(args.jobs) as pool:
            for i, (doc, res) in enumerate(pool.imap_unordered(run_one, docs), 1):
                got[doc] = res
                if i % 10 == 0:
                    print(f"  {i}/{len(docs)}（{time.time() - t0:.0f}秒）")
    else:
        for i, doc in enumerate(docs, 1):
            got[doc] = run_one(doc)[1]
            if i % 10 == 0:
                print(f"  {i}/{len(docs)}（{time.time() - t0:.0f}秒）")

    # 部分ごとに、正解あり／正解なし（空欄）に分けて数える
    stat = {p: collections.Counter() for p in PARTS}
    per_field = collections.defaultdict(lambda: {p: collections.Counter() for p in PARTS})
    misses = []
    for doc in docs:
        want = text_truth.get(doc) or {}
        for fid, pre in DATE_MAP.items():
            read = (got.get(doc) or {}).get(fid) or {}
            for p in PARTS:
                truth = norm_truth(want.get(f"{pre}_{JA[p]}"))
                mine = read.get(p)
                mine_s = "" if mine is None else str(int(mine))
                for bucket in (stat[p], per_field[fid][p]):
                    if truth and mine_s == truth:
                        bucket["正解"] += 1
                    elif truth and not mine_s:
                        bucket["抜け"] += 1
                    elif truth:
                        bucket["誤り"] += 1
                    elif mine_s:
                        bucket["余計"] += 1
                    else:
                        bucket["空欄一致"] += 1
                if truth and mine_s != truth and len(misses) < args.detail:
                    misses.append((doc, fid, JA[p], truth, mine_s or "（抜け）",
                                   read.get("raw", "")))

    print("\n■ 日付の部分ごと")
    print(f"  {'':4s} {'記入あり':>8s} {'正解':>6s} {'抜け':>6s} {'誤り':>6s}   {'正解率':>7s}")
    for p in PARTS:
        c = stat[p]
        n = c["正解"] + c["抜け"] + c["誤り"]
        rate = 100 * c["正解"] / n if n else 0.0
        print(f"  {JA[p]:4s} {n:8d} {c['正解']:6d} {c['抜け']:6d} {c['誤り']:6d}   {rate:6.1f}%")
    print(f"\n  空欄を空欄と判定: "
          + "、".join(f"{JA[p]} {stat[p]['空欄一致']}" for p in PARTS))
    print("  空欄に値を入れた: "
          + "、".join(f"{JA[p]} {stat[p]['余計']}" for p in PARTS))

    print("\n■ 欄ごとの「日」の正解率")
    for fid in DATE_MAP:
        c = per_field[fid]["day"]
        n = c["正解"] + c["抜け"] + c["誤り"]
        rate = 100 * c["正解"] / n if n else 0.0
        print(f"  {fid:18s} 記入あり {n:4d}  正解 {c['正解']:4d}  抜け {c['抜け']:4d}"
              f"  誤り {c['誤り']:3d}   {rate:5.1f}%")

    if misses:
        print("\n■ 外した箇所")
        for doc, fid, part, truth, mine, raw in misses:
            print(f"  {doc} {fid:18s} {part} 正解 {truth:>3s} / 読み {mine:>6s}   生読み: {raw}")
    print(f"\n所要 {time.time() - t0:.0f} 秒")


if __name__ == "__main__":
    main()
