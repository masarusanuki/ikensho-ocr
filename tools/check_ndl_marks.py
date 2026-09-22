# -*- coding: utf-8 -*-
"""NDLOCR が読んだチェック欄の状態が、照合に使えるかを測る。

**結果は「使えない」。** この道具は、その判断をやり直せるように残してある。

    python3 tools/check_ndl_marks.py --limit 4

NDLOCR はチェック欄が並んだ行を `□初回 ■2回目以上` のように読む。
そこで「行に塗られた印の数」をこちらの判定と突き合わせ、
食い違う行を要確認にする案を測った。実測（正解データ4通）は

    知らせた行 40 / うち本当に誤りを含む 0

で、1通あたり10行の空振り。こちらの判定（99.08%）の方がずっと正確なので、
食い違いはほぼ NDLOCR 側の読み違いだった。
"""
import argparse
import collections
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "python"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

from benchmark_seigo import box_ids, load_truth, pdf_path      # noqa: E402
from ikensho_ocr import align, checkbox, imaging, ndlocr        # noqa: E402
from ikensho_ocr.templates import load_templates                # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=4)
    args = ap.parse_args()

    truth = load_truth()
    cbt = truth["checkbox"]
    tpls = load_templates()
    ids = box_ids(tpls)
    docs = sorted(cbt)[:args.limit]
    stat = collections.Counter()
    print(f"{len(docs)} 通で測ります")

    for doc in docs:
        for sp in imaging.load_any(pdf_path(doc), imaging.DEFAULT_DPI):
            m = align.match_page(sp.image, tpls)
            if m is None:
                continue
            tpl = tpls[m.template_id]
            page = tpl.page(m.page_index)
            if page is None:
                continue
            blank = page.blank_image(tpl.base_dir)
            rs = checkbox.read_boxes(m.warped, page.boxes, blank)
            reader = ndlocr.PageReader(m.warped)
            H, W = m.warped.shape[:2]
            checked = {(r.field, r.opt): bool(r.checked) for r in rs}
            placed = []
            for b in page.boxes:
                x, y, w, h = b["rect"]
                placed.append(dict(field=b["field"], opt=b["opt"],
                                   cx=(x + w / 2) * W, cy=(y + h / 2) * H))
            for ml in ndlocr.mark_lines(reader):
                mine = [p for p in placed
                        if ml.y0 <= p["cy"] <= ml.y1
                        and ml.x0 - 12 <= p["cx"] <= ml.x1 + 12]
                if not mine or abs(len(mine) - ml.boxes) > 1:
                    continue
                ours = sum(1 for p in mine if checked.get((p["field"], p["opt"])))
                if ours == ml.filled:
                    continue
                # 知らせる行。その中に本当に誤りがあるか正解と突き合わせる
                fields = {p["field"] for p in mine}
                wrong = 0
                for r in rs:
                    if r.field not in fields:
                        continue
                    bid = ids.get((m.page_index, r.field, r.opt))
                    if bid is None or bid not in cbt.get(doc, {}):
                        continue
                    if int(r.checked) != cbt[doc][bid]:
                        wrong += 1
                stat["知らせた行"] += 1
                stat["うち本当に誤りを含む"] += int(wrong > 0)
                if wrong:
                    print(f"  当たり {doc}: 誤り{wrong}件 ← {ml.text[:50]}")

    n = stat["知らせた行"]
    hit = stat["うち本当に誤りを含む"]
    print(f"\n知らせた行 {n} / うち本当に誤りを含む {hit}"
          f"（{100 * hit / max(n, 1):.1f}%）")
    print("空振りが多ければ、この照合は入れない方がよい。")


if __name__ == "__main__":
    main()
