# -*- coding: utf-8 -*-
"""OCR エンジン／モデルを、正解データと突き合わせて測る。

正解は `bench/ocr_truth.json`（`tools/make_ocr_truth_sheet.py` で作った
切り抜き一覧を目視で書き取ったもの）。

    python3 tools/benchmark_ocr.py                       # 使えるものすべて
    python3 tools/benchmark_ocr.py --engines tesseract rapidocr
    python3 tools/benchmark_ocr.py --raw                 # 辞書補正の前で測る
    python3 tools/benchmark_ocr.py --update-docs         # 結果を DEVELOPER.md に反映

測る指標:

- **文字正解率** … 1 - 編集距離/正解の文字数（char accuracy）。0未満は0に丸める
- **完全一致** … 記入のある欄で、正解とぴたり同じだった割合
- **空欄の判定** … 記入が無い欄を空と判断できた割合（拾い読みをしない）

読み取りの手前（位置合わせ・欄の切り出し）は共通なので、
ここで測っているのは**文字を読む部分だけ**の違い。
"""
import argparse
import json
import os
import re
import sys
import time
import unicodedata

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "python"))

from ikensho_ocr import align, imaging, ocr as ocr_mod, textbox  # noqa: E402
from ikensho_ocr import proofread, text_check  # noqa: E402
from ikensho_ocr.dictionaries import DEFAULT_DICTIONARIES  # noqa: E402
from ikensho_ocr.schema import load_schema  # noqa: E402
from ikensho_ocr.templates import load_templates  # noqa: E402

TRUTH = os.path.join(ROOT, "bench", "ocr_truth.json")
MARK_START = "<!-- OCR_BENCH_START -->"
MARK_END = "<!-- OCR_BENCH_END -->"


def norm(s: str) -> str:
    """比べる前に、字体と空白のゆれを吸収する。"""
    s = unicodedata.normalize("NFKC", s or "")
    return re.sub(r"\s+", "", s)


def levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def char_accuracy(truth: str, got: str) -> float:
    t, g = norm(truth), norm(got)
    if not t:
        return 1.0 if not g else 0.0
    return max(0.0, 1.0 - levenshtein(t, g) / len(t))


def ink_bbox(warped, blank, rect, pad=0.35):
    """書き込みだけの矩形を返す（印刷された罫線・カッコを外す）。

    白紙様式との差分を見れば「印刷か、書き込みか」が分かる。
    罫線やカッコを切り落として文字に寄せた方が、認識モデルは読みやすいはず
    — という見当を確かめるために使う。
    """
    import numpy as np
    from ikensho_ocr import text_check
    diff = text_check.mark_layer(warped, blank)
    if diff is None:
        return rect
    H, W = diff.shape
    x, y, w, h = rect
    x0, y0 = max(0, int(x * W)), max(0, int(y * H))
    x1, y1 = min(W, int((x + w) * W)), min(H, int((y + h) * H))
    win = diff[y0:y1, x0:x1]
    if win.size == 0 or not (win > 0).any():
        return rect
    cols = np.where((win > 0).sum(axis=0) >= 1)[0]
    rows = np.where((win > 0).sum(axis=1) >= 1)[0]
    if len(cols) == 0 or len(rows) == 0:
        return rect
    # 文字の周りに少し余白を残す（詰めすぎると読めなくなる）
    mh = max(2, int((rows[-1] - rows[0] + 1) * pad))
    nx0 = max(x0, x0 + cols[0] - mh)
    nx1 = min(x1, x0 + cols[-1] + 1 + mh)
    ny0 = max(y0, y0 + rows[0] - mh)
    ny1 = min(y1, y0 + rows[-1] + 1 + mh)
    if nx1 - nx0 < 8 or ny1 - ny0 < 8:
        return rect
    return [nx0 / W, ny0 / H, (nx1 - nx0) / W, (ny1 - ny0) / H]


def crops(paths, ink_crop=True):
    """検体ごとに（項目, 切り抜き画像, 文字種）を集める。位置合わせは1回だけ。"""
    tpls = load_templates()
    schema = load_schema()
    by_id = {f.id: f for f in schema}
    out = {}
    for path in paths:
        base = os.path.basename(path)
        items = []
        for sp in imaging.load_any(path, imaging.DEFAULT_DPI):
            m = align.match_page(sp.image, tpls)
            if m is None:
                continue
            tpl = tpls[m.template_id]
            page = tpl.page(m.page_index)
            if page is None:
                continue
            blank = page.blank_image(tpl.base_dir)
            for t in page.texts:
                f = by_id.get(t["field"])
                if f is None or f.is_date or f.type == "circle":
                    continue
                rect = textbox.widen_left(blank, t["rect"])
                charset = t.get("charset") or getattr(f, "charset", "")
                if not ocr_mod.has_ink(m.warped, rect):
                    items.append((f, None, charset))       # 空欄と判断した欄
                    continue
                # 本体（extract.py）と同じ扱い: 書き込みが無い欄は読まない
                shape = text_check.written_shape(m.warped, blank, rect)
                if shape is not None and shape["density"] < text_check.EMPTY_DENSITY:
                    items.append((f, None, charset))
                    continue
                if ink_crop:
                    rect = ink_bbox(m.warped, blank, rect)
                items.append((f, ocr_mod.prepare_roi(m.warped, rect, pad=0.02), charset))
        out[base] = items
    return out


def run_engine(name, sheets, truth, use_dict=True):
    engine = ocr_mod.get_engine(name)
    if not engine.available:
        return None
    dicts = DEFAULT_DICTIONARIES() if use_dict else None
    tot = dict(n=0, acc=0.0, exact=0, filled=0, blank_ok=0, blank=0, sec=0.0,
               junk=0)
    rows = []
    for base, items in sheets.items():
        want = truth.get(base) or {}
        for f, roi, charset in items:
            if f.id not in want:
                continue
            expect = want[f.id]
            t0 = time.time()
            if roi is None:
                got = ""
            else:
                res = engine.read(roi, multiline=(f.type == "textarea"),
                                  charset=charset)
                got = res.text or ""
                if use_dict:
                    trimmed, _ = text_check.trim_edges(got)
                    pr = proofread.proofread_text(
                        trimmed, multiline=(f.type == "textarea"))
                    got, _conf, _cands = dicts.correct(f, pr.text, res.confidence)
            tot["sec"] += time.time() - t0
            acc = char_accuracy(expect, got)
            tot["n"] += 1
            tot["acc"] += acc
            if expect:
                tot["filled"] += 1
                if norm(expect) == norm(got):
                    tot["exact"] += 1
            else:
                tot["blank"] += 1
                if not norm(got):
                    tot["blank_ok"] += 1
                elif len(norm(got)) >= 2:
                    tot["junk"] += 1
            rows.append(dict(file=base, field=f.id, label=f.label,
                             truth=expect, got=got, acc=round(acc, 3)))
    return dict(engine=engine.name, totals=tot, rows=rows)


def report(result):
    t = result["totals"]
    return dict(
        engine=result["engine"],
        char=t["acc"] / max(t["n"], 1) * 100,
        exact=t["exact"] / max(t["filled"], 1) * 100,
        blank=t["blank_ok"] / max(t["blank"], 1) * 100,
        junk=t["junk"],
        sec=t["sec"],
        n=t["n"], filled=t["filled"],
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engines", nargs="*", default=None)
    ap.add_argument("--raw", action="store_true",
                    help="辞書補正・誤字訂正をかけずに、OCRの生の読みで測る")
    ap.add_argument("--samples", default=os.path.join(ROOT, "sample"))
    ap.add_argument("--detail", action="store_true", help="欄ごとの結果も出す")
    ap.add_argument("--no-ink-crop", action="store_true",
                    help="書き込みの範囲に切り詰めずに読む（比較用）")
    ap.add_argument("--out", default=None, help="結果をJSONで書き出す")
    ap.add_argument("--update-docs", action="store_true")
    args = ap.parse_args()

    with open(TRUTH, encoding="utf-8") as fh:
        truth = json.load(fh)["records"]
    paths = [os.path.join(args.samples, name) for name in truth]
    missing = [p for p in paths if not os.path.exists(p)]
    if missing:
        raise SystemExit("検体が見つかりません: " + ", ".join(missing))

    print(f"正解 {len(truth)} 検体 / "
          f"{sum(len(v) for v in truth.values())} 項目"
          f"（{'OCRの生読み' if args.raw else '辞書補正まで通した値'}で比較）\n")
    sheets = crops(paths, ink_crop=not args.no_ink_crop)
    print("（書き込みの範囲に切り詰めずに読みます）" if args.no_ink_crop
          else "（本体と同じ: 書き込みが無い欄は読まず、書き込みの範囲に切り詰めて読む）")

    names = args.engines or ["tesseract", "rapidocr", "mangaocr", "ensemble"]
    results, reports = [], []
    for name in names:
        res = run_engine(name, sheets, truth, use_dict=not args.raw)
        if res is None:
            print(f"  {name:12s} … 使えません（未導入）")
            continue
        results.append(res)
        reports.append(report(res))

    print(f"\n{'エンジン':22s} {'文字正解率':>9s} {'完全一致':>8s} "
          f"{'空欄の判定':>9s} {'拾い読み':>7s} {'所要':>7s}")
    for r in sorted(reports, key=lambda x: -x["char"]):
        print(f"  {r['engine']:20s} {r['char']:8.1f}% {r['exact']:7.1f}% "
              f"{r['blank']:8.1f}% {r['junk']:6d}件 {r['sec']:6.1f}秒")

    if args.detail:
        for res in results:
            print(f"\n=== {res['engine']}（正解と違う欄）")
            for row in sorted(res["rows"], key=lambda r: r["acc"]):
                if row["acc"] >= 0.999:
                    continue
                print(f"  {row['label'][:18]:20s} 正解「{row['truth'][:34]}」")
                print(f"  {'':20s} 読み「{row['got'][:34]}」 {row['acc']:.2f}")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(dict(raw=args.raw, reports=reports, results=results),
                      fh, ensure_ascii=False, indent=1)
        print(f"\n書き出し: {args.out}")

    if args.update_docs:
        update_docs(reports, args.raw)
    return reports


def update_docs(reports, raw):
    path = os.path.join(ROOT, "docs", "DEVELOPER.md")
    with open(path, encoding="utf-8") as fh:
        md = fh.read()
    lines = ["", f"| エンジン | 文字正解率 | 完全一致 | 空欄の判定 | 拾い読み | 所要 |",
             "|---|---:|---:|---:|---:|---:|"]
    for r in sorted(reports, key=lambda x: -x["char"]):
        lines.append(f"| {r['engine']} | {r['char']:.1f}% | {r['exact']:.1f}% | "
                     f"{r['blank']:.1f}% | {r['junk']}件 | {r['sec']:.1f}秒 |")
    lines += ["",
              f"（正解 {reports[0]['n']} 項目・うち記入あり {reports[0]['filled']} 項目。"
              f"{'OCRの生読み' if raw else '辞書補正まで通した値'}で比較。"
              "`python3 tools/benchmark_ocr.py --update-docs` で更新）", ""]
    block = MARK_START + "\n" + "\n".join(lines) + MARK_END
    if MARK_START in md:
        md = re.sub(re.escape(MARK_START) + r".*?" + re.escape(MARK_END),
                    block.replace("\\", "\\\\"), md, flags=re.S)
    else:
        md += "\n" + block + "\n"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(md)
    print(f"docs/DEVELOPER.md を更新しました")


if __name__ == "__main__":
    main()
