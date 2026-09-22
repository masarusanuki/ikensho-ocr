# -*- coding: utf-8 -*-
"""新しい検証データ（seigo2・1,000通）で測る。

これまでの正解データ（`seigo/`・100通）との違い:

  - **Word入力が350通** 含まれる（チェック項目の言葉が変わりうる）
  - 読みやすさが4段階（活字350 / 達筆227 / 汚い219 / 標準204）
  - チェックの表現が15通り（手書きのレ点から文字「■」「☑」まで）
  - スキャン風の加工が600通

チェック欄と文字欄を、**条件（mode / scan / 読みやすさ / チェック表現）ごとに**
切り分けて出す。まとめた正解率では、どの条件で崩れるのかが見えないため。

    python3 tools/benchmark_seigo2.py --limit 40 --jobs 6
    python3 tools/benchmark_seigo2.py --limit 40 --jobs 6 --by 読みやすさ
"""
import argparse
import collections
import csv
import difflib
import json
import os
import re
import sys
import time
import unicodedata

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "python"))
DATA = os.path.join(ROOT, "seigo2")

from ikensho_ocr import extract_record            # noqa: E402
from ikensho_ocr.schema import load_schema        # noqa: E402
from ikensho_ocr.templates import load_templates  # noqa: E402

# 正解データの項目名 → 我々の項目id
TEXT_MAP = {
    "記入日": "entry_date", "申請者氏名": "applicant_name",
    "ふりがな": "applicant_furigana", "郵便番号": "postal_code",
    "住所": "applicant_address", "生年月日": "birth_date", "年齢": "age",
    "連絡先": "applicant_phone", "医師氏名": "doctor_name",
    "医療機関名": "clinic_name", "電話": "clinic_phone", "FAX": "clinic_fax",
    "医療機関所在地": "clinic_address", "最終診察日": "last_exam_date",
    "診断名1": "diagnosis1_name", "診断名2": "diagnosis2_name",
    "診断名3": "diagnosis3_name", "発症年月日1": "diagnosis1_date",
    "発症年月日2": "diagnosis2_date", "発症年月日3": "diagnosis3_date",
    "不安定の状況": "stability_detail", "経過及び治療内容": "treatment_course",
    "身長": "height_cm", "体重": "weight_kg",
    "栄養上の留意点": "nutrition_note", "対処方針": "risk_policy",
    "医学的管理": "medical_management", "特記すべき事項": "special_notes",
}
# 単一選択（チェック欄）
CHOICE_MAP = {
    "同意": "consent", "意見書作成回数": "report_count",
    "他科受診の有無": "other_dept_visit", "性別": "applicant_sex",
    "症状の安定性": "symptom_stability",
    "障害高齢者自立度": "adl_disabled", "認知症高齢者自立度": "adl_dementia",
    "短期記憶": "short_term_memory", "認知能力": "decision_ability",
    "伝達能力": "communication_ability", "利き腕": "dominant_hand",
    "体重変化": "weight_change", "屋外歩行": "outdoor_walking",
    "車いす": "wheelchair", "歩行補助具": "walking_aid",
    "食事行為": "eating", "栄養状態": "nutrition_status",
    "改善の見通し": "service_outlook",
}
# 複数選択（「・」区切り）
MULTI_MAP = {
    "他科受診科目": "other_dept",
    # 正解データの「特別な医療」は、様式では3つの欄に分かれている。
    # 1つの欄だけに当てると、残り2つの言葉が丸ごと不正解になる
    "特別な医療": ("special_med_procedure", "special_med_response",
                   "special_med_incontinence"),
    "発生可能性の高い状態": "risk_conditions",
}


# 正解データと我々の出力で、書き方が違うところを揃える。
# **揃えないと、読めているのに誤りに数えてしまう**（実際に数えた）。
_ERA = re.compile(r"^(明治|大正|昭和|平成|令和|明|大|昭|平|令)")
# 電話・FAX・郵便番号は数字だけで比べる
_DIGITS_ONLY = ("applicant_phone", "clinic_phone", "clinic_fax", "postal_code")
# 日付は元号を落としてから比べる（元号は別項目、または様式に印刷済み）
_DATES = ("entry_date", "birth_date", "last_exam_date",
          "diagnosis1_date", "diagnosis2_date", "diagnosis3_date")
# ふりがなは、正解データがカタカナ・我々は平仮名（様式の欄名に合わせている）
_KANA = ("applicant_furigana",)


def _to_hira(text):
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in text)


def norm(text):
    """比べるための下ごしらえ（空白は落とす）。"""
    if text is None:
        return ""
    if isinstance(text, (list, tuple)):
        return "・".join(str(v) for v in text)
    if isinstance(text, bool):
        return "有" if text else ""
    return "".join(str(text).split())


def norm_for(fid, text):
    """欄ごとに、書き方の違いを吸収する。"""
    t = norm(text)
    if not t:
        return t
    t = unicodedata.normalize("NFKC", t)
    if fid in _DIGITS_ONLY:
        return re.sub(r"\D", "", t)
    if fid in _DATES:
        t = _ERA.sub("", t)
        # 「12」と「12日」のように末尾の単位が付く・付かないを揃える
        return t.rstrip("日") if t.endswith("日") else t
    if fid in _KANA:
        return _to_hira(t)
    return t


def ratio(fid, want, got):
    a, b = norm_for(fid, want), norm_for(fid, got)
    if not a and not b:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def is_exact(fid, want, got):
    return norm_for(fid, want) == norm_for(fid, got)


def _fields_of(schema, fid):
    """項目idは1つとは限らない（正解データの1項目が様式の複数欄に分かれる）。"""
    ids = fid if isinstance(fid, (list, tuple)) else (fid,)
    return [(i, schema.get(i)) for i in ids if schema.get(i) is not None]


def joined_value(got, fid):
    """複数の欄に分かれている項目を、正解データと同じ1つの値にまとめる。"""
    ids = fid if isinstance(fid, (list, tuple)) else (fid,)
    parts = []
    for i in ids:
        v = got.get(i)
        if isinstance(v, (list, tuple)):
            parts.extend(str(x) for x in v)
        elif v not in (None, "", False):
            parts.append(str(v))
    if len(ids) == 1:
        return got.get(ids[0])
    return parts


def expected_opts(pairs, want):
    """正解データの答えの言葉を、欄ごとの「印を付ける選択肢番号」にする。

    `seigo2` の正解データは**質問ごとの答えの言葉**しか持たないので、
    枠単位で数えるにはここで展開する。単一選択ならその1枠だけ印あり、
    複数選択なら挙がった言葉の枠に印あり、残りは印なしとみなす。

    **区切り文字で割ってはいけない。** 「転倒・骨折」のように選択肢そのものに
    「・」が入っているので、割ると「転倒」「骨折」に崩れる。
    長い選択肢から順に、文字列の中に出てくるものを拾う。

    どれにも寄せられない言葉が残ったときは None を返し、その項目は数えない
    （正解が作れないものを不正解として数えると、数字が嘘になる）。
    """
    if isinstance(want, (list, tuple)):
        text = "・".join(str(w) for w in want)
    else:
        text = str(want)
    rest = norm_for("", text)
    if not rest:
        return None
    # (欄id, 選択肢番号, 正規化した言葉) を長い順に
    cand = []
    for fid, f in pairs:
        for i, o in enumerate(f.options or []):
            no = norm_for("", str(o))
            if no:
                cand.append((fid, i, no))
    if not cand:
        return None
    picked = {fid: set() for fid, _ in pairs}
    for fid, i, no in sorted(cand, key=lambda c: -len(c[2])):
        if no in rest:
            picked[fid].add(i)
            rest = rest.replace(no, "", 1)
    rest = re.sub(r"[・,、／/\s]", "", rest)
    if rest:
        # 残った言葉が選択肢の言い回し違いなら拾う（「主に他人が操作」など）
        for fid, i, no in cand:
            if no.startswith(rest) or rest.startswith(no) or \
                    difflib.SequenceMatcher(None, rest, no).ratio() >= 0.75:
                picked[fid].add(i)
                rest = ""
                break
    if rest or not any(picked.values()):
        return None
    return picked


def load_truth():
    with open(os.path.join(DATA, "truth", "ground_truth.json"), encoding="utf-8") as fh:
        rows = json.load(fh)
    truth = {r["sample_id"]: r for r in rows}
    with open(os.path.join(DATA, "truth", "ground_truth.csv"),
              encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            truth.setdefault(r["sample_id"], {}).update(
                {k: v for k, v in r.items() if k not in truth.get(r["sample_id"], {})})
    return truth


def pdf_path(row):
    """正解データの行から PDF の場所を作る。"""
    return os.path.join(DATA, "samples", row["part"], row["file"])


def run_one(args_tuple):
    sid, path, engine = args_tuple
    schema = load_schema()
    templates = load_templates()
    try:
        rec = extract_record([path], schema=schema, templates=templates,
                             engine=engine, use_llm=False)
    except Exception as exc:
        return sid, None, str(exc)
    got, boxes = {}, {}
    for fid, e in rec.fields.items():
        got[fid] = e.get("value")
        detail = e.get("detail")
        if detail:
            # 枠ごとの印。**質問単位の文字列比較とは別に、枠単位でも数えるため**
            boxes[fid] = {int(d["opt"]): bool(d.get("checked"))
                          for d in detail if d.get("opt") is not None}
    return sid, (got, boxes), None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--jobs", type=int, default=1)
    ap.add_argument("--engine", default="auto")
    ap.add_argument("--by", default="mode",
                    help="切り分ける軸: mode / scan / 読みやすさ / チェック表現")
    ap.add_argument("--detail", type=int, default=0)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    truth = load_truth()
    schema_all = load_schema()
    ids = sorted(truth)
    if args.limit:
        # **軸ごとに同じ数ずつ取る。** 単に間引くと偏る
        # （1000通を25通おきに取ったら40通すべて手書きになった）
        groups = collections.defaultdict(list)
        for sid in ids:
            groups[truth[sid].get(args.by, "?")].append(sid)
        per = max(1, args.limit // max(len(groups), 1))
        picked = []
        for key in sorted(groups):
            picked.extend(groups[key][:per])
        ids = sorted(picked)[:max(args.limit, len(groups))]
    tasks = [(sid, pdf_path(truth[sid]), args.engine) for sid in ids]
    print(f"{len(ids)} 通で測ります（エンジン {args.engine}・軸 {args.by}）")

    results = {}
    t0 = time.time()
    if args.jobs > 1:
        import multiprocessing as mp
        with mp.Pool(args.jobs) as pool:
            for i, (sid, got, err) in enumerate(pool.imap_unordered(run_one, tasks), 1):
                results[sid] = (got, err)
                if i % 5 == 0:
                    print(f"  {i}/{len(ids)}（{time.time() - t0:.0f}秒）", flush=True)
    else:
        for i, t in enumerate(tasks, 1):
            sid, got, err = run_one(t)
            results[sid] = (got, err)
            if i % 5 == 0:
                print(f"  {i}/{len(ids)}（{time.time() - t0:.0f}秒）", flush=True)

    # 集計
    total = collections.defaultdict(lambda: [0.0, 0, 0])      # 文字率, 件数, 完全一致
    by_axis = collections.defaultdict(lambda: collections.defaultdict(
        lambda: [0.0, 0, 0]))
    per_field = collections.defaultdict(lambda: [0.0, 0, 0])
    misses = []
    errs = 0
    box_total = box_ok = box_miss = box_false = 0
    for sid in ids:
        payload, err = results.get(sid, (None, "未実行"))
        got, boxes = payload if payload else (None, {})
        if got is None:
            errs += 1
            continue
        want = truth[sid]
        axis = want.get(args.by, "?")
        for jname, fid in list(TEXT_MAP.items()) + list(CHOICE_MAP.items()) \
                + list(MULTI_MAP.items()):
            expect = want.get(jname)
            if expect is None or not str(expect).strip():
                continue
            mine = joined_value(got, fid)
            r = ratio(fid, expect, mine)
            exact = int(is_exact(fid, expect, mine))
            kind = ("文字" if jname in TEXT_MAP else "チェック")
            key = "+".join(fid) if isinstance(fid, (list, tuple)) else fid
            for bucket in (total[kind], by_axis[kind][axis], per_field[key]):
                bucket[0] += r
                bucket[1] += 1
                bucket[2] += exact
            if kind == "チェック":
                pairs = _fields_of(schema_all, fid)
                exp = expected_opts(pairs, expect) if pairs else None
                if exp is not None:
                    for one, _f in pairs:
                        want_set = exp.get(one, set())
                        for opt, checked in sorted(boxes.get(one, {}).items()):
                            box_total += 1
                            if checked == (opt in want_set):
                                box_ok += 1
                            elif opt in want_set:
                                box_miss += 1
                            else:
                                box_false += 1
            if len(misses) < args.detail and not exact:
                misses.append((sid, want.get("mode"), want.get("読みやすさ"),
                               fid, expect, mine))

    print(f"\n■ 全体（{len(ids) - errs} 通・読めなかった {errs} 通）")
    if box_total:
        # `seigo/` と同じ数え方（□ひとつを1件・0か1）。
        # 質問単位の文字列の近さとは**別の数字**なので、並べて出す
        print(f"  枠単位   正解率 {100 * box_ok / box_total:6.2f}%  "
              f"（{box_total} 枠・見落とし {box_miss} / 誤検出 {box_false}）")
    for kind in ("チェック", "文字"):
        s = total[kind]
        if not s[1]:
            continue
        print(f"  {kind:6s} 正解率 {100 * s[0] / s[1]:6.2f}%  "
              f"完全一致 {100 * s[2] / s[1]:6.2f}%  （{s[1]} 件）")

    print(f"\n■ {args.by} ごと")
    axes = sorted({want.get(args.by, "?") for want in
                   (truth[s] for s in ids)})
    print(f"  {'':28s} " + "".join(f"{k[:14]:>16s}" for k in ("チェック", "文字")))
    for a in axes:
        row = f"  {str(a)[:26]:28s} "
        for kind in ("チェック", "文字"):
            s = by_axis[kind].get(a)
            row += (f"{100 * s[0] / s[1]:15.1f}%" if s and s[1] else f"{'—':>16s}")
        print(row)

    print("\n■ 欄ごと（悪い順・上位18）")
    rows = sorted(((100 * v[0] / v[1], 100 * v[2] / v[1], k, v[1])
                   for k, v in per_field.items() if v[1]), key=lambda x: x[0])
    for acc, exact, fid, n in rows[:18]:
        print(f"  {fid:26s} 正解率 {acc:6.2f}%  完全一致 {exact:6.2f}%  ({n}件)")

    if misses:
        print("\n■ 外した例")
        for sid, mode, read, fid, expect, mine in misses:
            print(f"  {sid} [{mode}/{read}] {fid}")
            print(f"    正解「{norm(expect)}」 → 揃えると「{norm_for(fid, expect)}」")
            print(f"    読み「{norm(mine)}」 → 揃えると「{norm_for(fid, mine)}」")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(dict(
                total={k: v for k, v in total.items()},
                by_axis={k: dict(v) for k, v in by_axis.items()},
                per_field=dict(per_field), errs=errs, n=len(ids)), fh,
                ensure_ascii=False, indent=1)
        print(f"\n書き出し: {args.out}")
    print(f"\n所要 {time.time() - t0:.0f} 秒")


if __name__ == "__main__":
    main()
