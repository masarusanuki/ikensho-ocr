# -*- coding: utf-8 -*-
"""正解データ100通（seigo/）で、チェック判定とテキスト読み取りを測る。

`seigo/extracted/` にある正解（`ground_truth_checkbox.csv` /
`ground_truth_text.csv` / `ground_truth_marks.csv`）と突き合わせる。
チェック枠186個は、位置で我々のテンプレートと1対1に対応することを確認済み。

    python3 tools/benchmark_seigo.py --limit 10          # まず10通で見る
    python3 tools/benchmark_seigo.py --jobs 4            # 100通を並列で
    python3 tools/benchmark_seigo.py --marks             # 印の種類別に出す
    python3 tools/benchmark_seigo.py --text --limit 10   # テキストも測る（遅い）
    python3 tools/benchmark_seigo.py --detail 20         # 外した箇所を並べる

チェック判定は3つに分けて見る（正解データの README に合わせた）。

- 見落とし  … 印があって正解1のもの（Recall）
- 訂正の誤り … 印はあるが二重線で消してあり、正解0のもの（いちばん間違えやすい）
- 誤検出    … 印が無いのに1と答えたもの（Precision）
"""
import argparse
import csv
import json
import os
import sys
import time
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "python"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

SEIGO = os.path.join(ROOT, "seigo")
TRUTH_DIR = os.path.join(SEIGO, "extracted")
PDF_DIRS = [
    os.path.join(SEIGO, "files", "ikensho100_pdf_part1_0001-0034"),
    os.path.join(SEIGO, "files", "ikensho100_pdf_part2_0035-0067"),
    os.path.join(SEIGO, "files", "ikensho100_pdf_part3_0068-0100"),
]

# 正解データの項目名 → 我々の項目id
#   日付は「_年」「_月」「_日」に分かれているので、まとめて1つの欄に対応させる
TEXT_MAP = {
    "ふりがな": "applicant_furigana",
    "氏名": "applicant_name",
    "申請者住所": "applicant_address",
    "年齢": "age",
    "医師氏名": "doctor_name",
    "医療機関名": "clinic_name",
    "医療機関所在地": "clinic_address",
    "診断名1": "diagnosis1_name",
    "診断名2": "diagnosis2_name",
    "診断名3": "diagnosis3_name",
    "経過及び治療内容": "treatment_course",
    "身長": "height_cm",
    "体重": "weight_kg",
    "特記すべき事項": "special_notes",
    "筋力低下部位": "muscle_weakness_site",
    "痛み部位": "joint_pain_site",
    "拘縮部位": "joint_contracture_site",
    "褥瘡部位": "pressure_ulcer_site",
    "留意事項_摂食": "caution_eating_text",
    "留意事項_嚥下": "caution_swallow_text",
    "留意事項_血圧": "caution_bp_text",
    "留意事項_移動": "caution_move_text",
    "留意事項_運動": "caution_exercise_text",
    "留意事項_その他": "caution_other_text",
    "栄養食生活の留意点": "nutrition_note",
    "対処方針": "risk_policy",
    "不安定の状況": "stability_detail",
    "感染症": "infection_detail",
}
# 「市外局番＋番号」で1つの欄になるもの
JOIN_MAP = {
    "postal_code": ("郵便番号1", "郵便番号2", "-"),
    "applicant_phone": ("連絡先_市外", "連絡先_番号", "-"),
    "clinic_phone": ("医療機関電話_市外", "医療機関電話_番号", "-"),
    "clinic_fax": ("FAX_市外", "FAX_番号", "-"),
}
# 年・月・日に分かれている日付欄
DATE_MAP = {
    "entry_date": "記入日",
    "birth_date": "生年月日",
    "last_exam_date": "最終診察日",
    "diagnosis1_date": "発症1",
    "diagnosis2_date": "発症2",
    "diagnosis3_date": "発症3",
}


def load_truth():
    def read(name):
        with open(os.path.join(TRUTH_DIR, name), encoding="utf-8-sig") as fh:
            return list(csv.DictReader(fh))

    text = defaultdict(dict)
    for r in read("ground_truth_text.csv"):
        text[r["文書"]][r["項目"]] = r["正解値"]
    checkbox = {}
    with open(os.path.join(TRUTH_DIR, "ground_truth_checkbox.csv"),
              encoding="utf-8-sig") as fh:
        reader = csv.reader(fh)
        header = next(reader)
        ids = [h.split(":")[0] for h in header[1:]]
        for row in reader:
            checkbox[row[0]] = {i: int(v) for i, v in zip(ids, row[1:])}
    marks = defaultdict(dict)
    for r in read("ground_truth_marks.csv"):
        marks[r["文書"]][r["ID"]] = dict(kind=r["印の種類"], judge=int(r["判定"]),
                                         label=r["ラベル"])
    docs = {r["文書"]: r for r in read("documents.csv")}
    return dict(text=text, checkbox=checkbox, marks=marks, docs=docs, ids=ids)


def pdf_path(doc):
    for d in PDF_DIRS:
        p = os.path.join(d, doc + ".pdf")
        if os.path.exists(p):
            return p
    return None


def box_ids(templates):
    """我々のテンプレートの枠を、正解データの ID（p0_000…）に対応させる。

    位置で突き合わせて 186/186 一致することを確認済みなので、
    ページごとの並び順で対応させる。
    """
    with open(os.path.join(TRUTH_DIR, "checkboxes.json"), encoding="utf-8") as fh:
        cb = json.load(fh)
    out = {}
    tpl = templates["official_v1"]
    for page_i, page in enumerate(tpl.pages):
        theirs = [c for c in cb if c["page"] == page_i]
        if len(theirs) != len(page.boxes):
            raise SystemExit(f"枠の数が合いません page{page_i}: "
                             f"{len(theirs)} vs {len(page.boxes)}")
        for c, b in zip(theirs, page.boxes):
            out[(page.index, b["field"], b["opt"])] = c["id"]
    return out


def run_one(args):
    """1通を読み取り、枠ごとの判定とテキストを返す（並列実行のため関数に切る）。"""
    doc, want_text, engine_name = args
    from ikensho_ocr import align, checkbox as cb_mod, imaging
    from ikensho_ocr.templates import load_templates
    from ikensho_ocr.schema import load_schema
    path = pdf_path(doc)
    if not path:
        return doc, None
    templates = load_templates()
    mapping = box_ids(templates)
    t0 = time.time()
    boxes = {}
    for sp in imaging.load_any(path, imaging.DEFAULT_DPI):
        m = align.match_page(sp.image, templates)
        if m is None:
            continue
        tpl = templates[m.template_id]
        page = tpl.page(m.page_index)
        if page is None:
            continue
        blank = page.blank_image(tpl.base_dir)
        for r in cb_mod.read_boxes(m.warped, page.boxes, blank):
            key = mapping.get((m.page_index, r.field, r.opt))
            if key:
                boxes[key] = dict(checked=bool(r.checked), score=round(r.score, 3),
                                  fill=round(r.fill, 3), mark=round(r.mark, 3),
                                  halo=round(r.halo, 3), circled=bool(r.circled),
                                  method=r.method)
    text = {}
    if want_text:
        from ikensho_ocr.extract import extract_record
        rec = extract_record([path], schema=load_schema(), templates=templates,
                             engine=engine_name, use_llm=False)
        for fid, e in rec.fields.items():
            if isinstance(e, dict):
                text[fid] = dict(value=e.get("value"), date=e.get("date"))
    return doc, dict(boxes=boxes, text=text, sec=round(time.time() - t0, 1))


def score_checkbox(truth, results, show_marks=False, detail=0):
    tp = fp = fn = tn = 0
    struck_ok = struck_ng = 0
    by_kind = defaultdict(lambda: [0, 0])     # 種類 → [正解, 件数]
    misses, falses, struck_bad = [], [], []
    for doc, got in results.items():
        want = truth["checkbox"].get(doc) or {}
        marks = truth["marks"].get(doc) or {}
        for bid, expect in want.items():
            pred = 1 if (got["boxes"].get(bid) or {}).get("checked") else 0
            info = marks.get(bid)
            if expect and pred:
                tp += 1
            elif expect and not pred:
                fn += 1
                misses.append((doc, bid, info["label"] if info else "",
                               info["kind"] if info else "", got["boxes"].get(bid)))
            elif not expect and pred:
                fp += 1
                if info:            # 印はあるが訂正されている
                    struck_ng += 1
                    struck_bad.append((doc, bid, info["label"], info["kind"],
                                       got["boxes"].get(bid)))
                else:
                    falses.append((doc, bid, got["boxes"].get(bid)))
            else:
                tn += 1
                if info:
                    struck_ok += 1
            if info:
                ok = (pred == expect)
                by_kind[info["kind"]][0] += int(ok)
                by_kind[info["kind"]][1] += 1
    total = tp + fp + fn + tn
    print(f"\n■ チェック判定 {total:,} 件（{len(results)} 通）")
    print(f"  正解率      {100 * (tp + tn) / max(total, 1):6.2f}%")
    print(f"  見落とし    {fn:4d} 件 / 印あり正解1 {tp + fn:,} 件"
          f"（Recall {100 * tp / max(tp + fn, 1):.2f}%）")
    print(f"  誤検出      {len(falses):4d} 件 / 印なし {tn + fp - struck_ng:,} 件")
    print(f"  訂正の誤り  {struck_ng:4d} 件 / 二重線で消した箇所 "
          f"{struck_ok + struck_ng:,} 件"
          f"（正しく0にできた {struck_ok}）")
    if show_marks:
        print("\n  印の種類ごとの正解率:")
        for kind, (ok, n) in sorted(by_kind.items(), key=lambda kv: kv[1][0] / max(kv[1][1], 1)):
            print(f"    {kind:16s} {100 * ok / max(n, 1):6.2f}%  ({ok}/{n})")
    if detail:
        for title, rows in (("見落とし", misses), ("訂正を1と答えた", struck_bad),
                            ("誤検出", falses)):
            if not rows:
                continue
            print(f"\n  【{title}】{len(rows)} 件（先頭 {min(detail, len(rows))} 件）")
            for r in rows[:detail]:
                print(f"    {r[0]} {r[1]} {str(r[2])[:18]:20s} {str(r[3])[:12]:14s} {r[-1]}")
    return dict(total=total, acc=(tp + tn) / max(total, 1), fn=fn, fp=fp,
                struck_ng=struck_ng, by_kind={k: v for k, v in by_kind.items()})


def score_text(truth, results, detail=0):
    from benchmark_ocr import char_accuracy, norm
    per_field = defaultdict(lambda: [0.0, 0, 0])   # 文字正解率合計, 件数, 完全一致
    rows = []
    for doc, got in results.items():
        if not got["text"]:
            continue
        want = truth["text"].get(doc) or {}

        def expect_of(fid):
            if fid in DATE_MAP:
                pre = DATE_MAP[fid]
                # 元年は正解データでは「元」と書かれている。読み取りは 1 を返すので
                # そろえる（そろえないと、正しく読めているのに誤りに数えてしまう）
                parts = [("1" if (want.get(f"{pre}_{k}") or "").strip() in ("元", "元年")
                          else want.get(f"{pre}_{k}"))
                         for k in ("年", "月", "日")]
                if not any(parts):
                    return None
                marks = ("年", "月", "日")
                return "".join(f"{v}{m}" for v, m in zip(parts, marks) if v)
            if fid in JOIN_MAP:
                a, b, sep = JOIN_MAP[fid]
                if not want.get(a) and not want.get(b):
                    return None
                return sep.join(x for x in (want.get(a), want.get(b)) if x)
            key = next((k for k, v in TEXT_MAP.items() if v == fid), None)
            return want.get(key) if key else None

        for fid in list(TEXT_MAP.values()) + list(JOIN_MAP) + list(DATE_MAP):
            expect = expect_of(fid)
            if expect is None:
                continue
            e = got["text"].get(fid) or {}
            value = e.get("value")
            value = "" if value is None else str(value)
            acc = char_accuracy(expect, value)
            per_field[fid][0] += acc
            per_field[fid][1] += 1
            per_field[fid][2] += int(norm(expect) == norm(value))
            rows.append((acc, doc, fid, expect, value))
    n = sum(v[1] for v in per_field.values())
    if not n:
        return None
    acc = sum(v[0] for v in per_field.values()) / n
    exact = sum(v[2] for v in per_field.values()) / n
    print(f"\n■ テキスト読み取り {n:,} 件")
    print(f"  文字正解率  {100 * acc:6.2f}%")
    print(f"  完全一致    {100 * exact:6.2f}%")
    print("\n  項目ごと（悪い順）:")
    for fid, (s, c, ex) in sorted(per_field.items(), key=lambda kv: kv[1][0] / max(kv[1][1], 1))[:18]:
        print(f"    {fid:26s} 文字 {100 * s / max(c, 1):6.2f}%  "
              f"完全一致 {100 * ex / max(c, 1):6.2f}%  ({c}件)")
    if detail:
        print(f"\n  【外した欄】先頭 {detail} 件")
        for acc_, doc, fid, expect, value in sorted(rows)[:detail]:
            print(f"    {doc} {fid:24s} {acc_:.2f}")
            print(f"      正解「{expect[:44]}」")
            print(f"      読み「{value[:44]}」")
    return dict(n=n, acc=acc, exact=exact)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="測る通数（既定: 全部）")
    ap.add_argument("--jobs", type=int, default=1)
    ap.add_argument("--text", action="store_true", help="テキストも測る（遅い）")
    ap.add_argument("--marks", action="store_true", help="印の種類ごとに出す")
    ap.add_argument("--detail", type=int, default=0, help="外した箇所を並べる")
    ap.add_argument("--engine", default="auto")
    ap.add_argument("--out", default=None, help="結果をJSONで書き出す")
    args = ap.parse_args()

    truth = load_truth()
    docs = sorted(truth["checkbox"])
    if args.limit:
        docs = docs[:args.limit]
    print(f"{len(docs)} 通で測ります"
          f"（{'チェック＋テキスト' if args.text else 'チェックのみ'}）")

    t0 = time.time()
    results = {}
    tasks = [(d, args.text, args.engine) for d in docs]
    if args.jobs > 1:
        import multiprocessing as mp
        with mp.Pool(args.jobs) as pool:
            for i, (doc, res) in enumerate(pool.imap_unordered(run_one, tasks), 1):
                if res:
                    results[doc] = res
                if i % 10 == 0:
                    print(f"  {i}/{len(docs)} 通（{time.time() - t0:.0f}秒）")
    else:
        for i, task in enumerate(tasks, 1):
            doc, res = run_one(task)
            if res:
                results[doc] = res
            if i % 10 == 0:
                print(f"  {i}/{len(docs)} 通（{time.time() - t0:.0f}秒）")

    cb = score_checkbox(truth, results, show_marks=args.marks, detail=args.detail)
    tx = score_text(truth, results, detail=args.detail) if args.text else None
    print(f"\n所要 {time.time() - t0:.0f} 秒")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(dict(checkbox=cb, text=tx, results=results), fh,
                      ensure_ascii=False, indent=1)
        print(f"書き出し: {args.out}")


if __name__ == "__main__":
    main()
