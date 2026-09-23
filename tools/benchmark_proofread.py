# -*- coding: utf-8 -*-
"""LLM の校正が、文字欄の正解率を**上げているか下げているか**を測る。

校正は「直る」ことより「壊さない」ことが大事なので、
上がった件数だけでなく**下がった件数と中身**を必ず出す。

    .venv/bin/python tools/benchmark_proofread.py --limit 8 --jobs 4
    .venv/bin/python tools/benchmark_proofread.py --limit 8 --model models/xxx.gguf
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

from ikensho_ocr import extract_record, proofread                 # noqa: E402
from ikensho_ocr import llm as llm_mod                            # noqa: E402
from ikensho_ocr.schema import load_schema                        # noqa: E402
from ikensho_ocr.templates import load_templates                  # noqa: E402

import benchmark_seigo2 as B                                      # noqa: E402


def ratio(a, b):
    return difflib.SequenceMatcher(None, a or "", b or "").ratio()


def run(sid, row, model):
    """1通ぶん。校正前の値と校正後の値を両方返す。"""
    schema = load_schema()
    path = B.pdf_path(row)
    rec = extract_record([path], schema=schema, templates=load_templates(),
                         engine="auto", use_llm=False)      # まず校正なしで読む
    assist = llm_mod.LlmAssist(model_path=model)
    if not assist.available:
        return None
    out = []
    for jname, fid in B.TEXT_MAP.items():
        want = row.get(jname)
        if want is None or not str(want).strip():
            continue
        f = schema.get(fid)
        e = rec.fields.get(fid)
        if f is None or e is None:
            continue
        from ikensho_ocr.extract import _wants_proofread
        if not _wants_proofread(f, e, True):
            continue
        before = e.get("value") or ""
        lp = proofread.proofread_with_llm(assist, before, f.label)
        after = lp.text if lp else before
        out.append((fid, str(want), before, after, e.get("confidence")))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=8)
    ap.add_argument("--model", default=None, help="GGUF のパス（既定は自動選択）")
    ap.add_argument("--by", default="読みやすさ")
    args = ap.parse_args()

    truth = B.load_truth()
    ids = sorted(truth)
    groups = collections.defaultdict(list)
    for sid in ids:
        groups[truth[sid].get(args.by, "?")].append(sid)
    per = max(1, args.limit // max(len(groups), 1))
    picked = sorted(sum([g[:per] for g in groups.values()], []))[:args.limit]

    print(f"{len(picked)} 通で測ります（モデル {args.model or '自動'}）")
    t0 = time.time()
    before_sum = after_sum = 0.0
    n = 0
    up = down = same = 0
    worse = []
    for i, sid in enumerate(picked, 1):
        res = run(sid, truth[sid], args.model)
        if res is None:
            print("LLM が使えません"); return 1
        for fid, want, before, after, conf in res:
            b = B.ratio(fid, want, before)
            a = B.ratio(fid, want, after)
            before_sum += b; after_sum += a; n += 1
            if a > b + 1e-9:
                up += 1
            elif a < b - 1e-9:
                down += 1
                worse.append((sid, fid, want, before, after, conf))
            else:
                same += 1
        print(f"  {i}/{len(picked)}（{time.time() - t0:.0f}秒）", flush=True)

    if not n:
        print("測る欄がありませんでした"); return 1
    print(f"\n■ 校正の効き（{n} 欄）")
    print(f"  文字正解率  校正前 {before_sum / n * 100:6.2f}%"
          f" → 校正後 {after_sum / n * 100:6.2f}%")
    print(f"  上がった {up} 件 / 下がった {down} 件 / 変わらず {same} 件")
    if worse:
        print("\n■ 下がった欄（壊していないか必ず見ること）")
        for sid, fid, want, before, after, conf in worse[:12]:
            print(f"  {sid} {fid}（確信度 {conf}）")
            print(f"    正解: {want}")
            print(f"    読み: {before}")
            print(f"    校正: {after}")
    print(f"\n所要 {time.time() - t0:.0f} 秒")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
