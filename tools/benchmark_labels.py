# -*- coding: utf-8 -*-
"""チェック欄の「後ろの言葉」を、読み方ごとに比べる。

様式を Word で作り直すと**チェック項目の言葉そのものが変わる**ことがある。
そこを読めるかどうかで、出力が実物と合うかが決まる。

    いま   … 行ごとに切り出して PP-OCR（`labels.read_labels`）
    NDL行  … NDLOCR でページを読み、行の文字から言葉を取り出す

    python3 tools/benchmark_labels.py --limit 4
"""
import argparse
import collections
import difflib
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "python"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

from ikensho_ocr import align, imaging, labels as labels_mod, ndlocr  # noqa: E402
from ikensho_ocr import ocr as ocr_mod                                # noqa: E402
from ikensho_ocr.schema import load_schema                            # noqa: E402
from ikensho_ocr.templates import load_templates                      # noqa: E402

# 行の文字から印と言葉を切り出す。NDLOCR は □ を 口 と読むことがある
SPLIT = re.compile(f"[{re.escape(ndlocr.FILLED_CHARS + ndlocr.EMPTY_CHARS)}]")


def labels_from_lines(reader, boxes, width, height):
    """NDLOCR が読んだ行から、枠ごとの言葉を取り出す。

    行は `■有 □無` や `□初回 ■2回目以上` のように読まれる。
    **印の字で切ると、その後ろが言葉になる。** 切れた順に、
    その行にある枠を左から並べて突き合わせる。
    """
    out = {}
    placed = []
    for b in boxes:
        x, y, w, h = b["rect"]
        placed.append(dict(key=f"{b['field']}.{b['opt']}",
                           cx=(x + w / 2) * width, cy=(y + h / 2) * height))
    for line in reader.lines:
        marks = list(SPLIT.finditer(line.text))
        if not marks:
            continue
        # 印で切って、後ろの言葉を拾う
        words = []
        for i, m in enumerate(marks):
            end = marks[i + 1].start() if i + 1 < len(marks) else len(line.text)
            words.append(line.text[m.end():end].strip())
        mine = [p for p in placed
                if line.y0 <= p["cy"] <= line.y1
                and line.x0 - 12 <= p["cx"] <= line.x1 + 12]
        mine.sort(key=lambda p: p["cx"])
        if not mine or len(mine) != len(words):
            continue           # 数が合わないなら振り分けられない
        for p, w in zip(mine, words):
            if w:
                out[p["key"]] = w
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=4, help="測る通数（0で白紙様式のみ）")
    ap.add_argument("--detail", type=int, default=12)
    args = ap.parse_args()

    tpls = load_templates()
    schema = load_schema()
    eng = ocr_mod.get_engine("auto")

    # 測る相手: 白紙様式（いちばん条件が良い）と、記入済みの検体
    targets = [("白紙様式", None)]
    if args.limit:
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        from benchmark_seigo import load_truth, pdf_path
        for doc in sorted(load_truth()["checkbox"])[:args.limit]:
            targets.append((doc, pdf_path(doc)))

    stat = {w: [0, 0, 0.0] for w in ("いま", "NDL行")}   # 完全一致, 件数, 類似度合計
    # 2つの読みが一致したときに、それが正しいか（食い違いの合図に使えるか）
    agree = collections.Counter()
    miss = []
    times = collections.Counter()
    for name, path in targets:
        pages = []
        if path is None:
            tpl = tpls["official_v1"]
            for pg in tpl.pages:
                img = pg.blank_image(tpl.base_dir)
                if img is not None:
                    pages.append((pg, img))
        else:
            for sp in imaging.load_any(path, imaging.DEFAULT_DPI):
                m = align.match_page(sp.image, tpls)
                if m is None:
                    continue
                pg = tpls[m.template_id].page(m.page_index)
                if pg is not None:
                    pages.append((pg, m.warped))
        for pg, img in pages:
            t0 = time.time()
            cur = labels_mod.read_labels(img, pg.boxes, eng)
            times["いま"] += time.time() - t0
            t0 = time.time()
            reader = ndlocr.PageReader(img)
            ndl = labels_from_lines(reader, pg.boxes, img.shape[1], img.shape[0])
            times["NDL行"] += time.time() - t0
            for b in pg.boxes:
                f = schema.get(b["field"])
                if f is None or not f.options or b["opt"] >= len(f.options):
                    continue
                key = f"{b['field']}.{b['opt']}"
                want = f.options[b["opt"]]
                row = {}
                for way, got in (("いま", cur), ("NDL行", ndl)):
                    mine = got.get(key, "")
                    a = labels_mod.normalize(want)
                    c = labels_mod.normalize(mine)
                    r = difflib.SequenceMatcher(None, a, c).ratio() if (a and c) else 0.0
                    stat[way][0] += int(a == c)
                    stat[way][1] += 1
                    stat[way][2] += r
                    row[way] = mine
                if len(miss) < args.detail and row["いま"] and not row["NDL行"]:
                    pass
                if (len(miss) < args.detail
                        and labels_mod.normalize(row["NDL行"]) == labels_mod.normalize(want)
                        and labels_mod.normalize(row["いま"]) != labels_mod.normalize(want)):
                    miss.append((name, key, want, row))
                # 2つの読みが一致したかどうかで分けて数える
                a = labels_mod.normalize(row["いま"])
                b = labels_mod.normalize(row["NDL行"])
                w = labels_mod.normalize(want)
                if a and b and a == b:
                    agree["一致した"] += 1
                    agree["うち正しい"] += int(a == w)
                elif a and b:
                    agree["食い違った"] += 1
                    agree["食い違いのうち いまが正しい"] += int(a == w)
                    agree["食い違いのうち NDLが正しい"] += int(b == w)
                else:
                    agree["どちらかが空"] += 1
                    agree["空でない方が正しい"] += int((a or b) == w)

    print(f"\n■ チェック欄の言葉（{stat['いま'][1]} 枠）")
    print(f"  {'読み方':8s} {'完全一致':>9s} {'似かた':>9s} {'所要':>8s}")
    for way in ("いま", "NDL行"):
        exact, n, sim = stat[way]
        print(f"  {way:8s} {100 * exact / max(n, 1):8.2f}% {100 * sim / max(n, 1):8.2f}%"
              f" {times[way]:7.0f}秒")
    n_ag = agree["一致した"]
    print(f"\n■ 2つの読みを突き合わせる")
    print(f"  一致した            {n_ag:4d} 枠  うち正しい {agree['うち正しい']:4d}"
          f"（{100 * agree['うち正しい'] / max(n_ag, 1):.1f}%）")
    n_dis = agree["食い違った"]
    print(f"  食い違った          {n_dis:4d} 枠  いまが正しい"
          f" {agree['食い違いのうち いまが正しい']:3d} / NDLが正しい"
          f" {agree['食い違いのうち NDLが正しい']:3d}")
    n_e = agree["どちらかが空"]
    print(f"  どちらかが空        {n_e:4d} 枠  空でない方が正しい"
          f" {agree['空でない方が正しい']:3d}"
          f"（{100 * agree['空でない方が正しい'] / max(n_e, 1):.1f}%）")
    print("\n  → 一致したときの正しさが高ければ、"
          "『2つが一致して定義と違う』を食い違いの合図に使える")
    if miss:
        print("\n■ NDL行だけが当てた例")
        for name, key, want, row in miss:
            print(f"  {name} {key}  正解「{want}」")
            print(f"    いま 「{row['いま']}」 / NDL行「{row['NDL行']}」")


if __name__ == "__main__":
    main()
