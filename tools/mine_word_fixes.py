# -*- coding: utf-8 -*-
"""OCR の読み崩れを正解と突き合わせて、誤字表（WORD_FIXES）の候補を拾う。

**拾う通と測る通を必ず分ける。** 同じ通から拾って同じ通で測れば
必ず良くなるが、それは何も言っていないのと同じ。

    # 1. 読み取り結果と正解の対を1回だけ落とす（時間がかかるのはここだけ）
    .venv/bin/python tools/mine_word_fixes.py dump --limit 60 --jobs 6

    # 2. 以後はこのファイルだけで、拾い方を何度でも試せる
    .venv/bin/python tools/mine_word_fixes.py mine --train 40 --min-count 2

安全のための決まり:

  - **誤りの側が、正解データのどこにも本物として現れない**こと。
    「関食」が正解文に一度も出てこないなら、置き換えて構わない。
    出てくるなら、それは本物の語なので触らない
  - 同じ誤りが2つ以上の正解に対応するなら捨てる（どちらに直すか決まらない）
  - 1文字だけの置き換えは採らない。文脈なしに1字を置き換えるのは危ない
"""
import argparse
import collections
import difflib
import json
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "python"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

from ikensho_ocr import extract_record                       # noqa: E402
from ikensho_ocr.schema import load_schema                   # noqa: E402
from ikensho_ocr.templates import load_templates             # noqa: E402

import benchmark_seigo2 as B                                 # noqa: E402

PAIRS = os.path.join(ROOT, "bench", "seigo2_text_pairs.json")

# 拾う語の長さ（誤りの側）。1文字は文脈なしに置き換えると危ない
MIN_LEN = 2
MAX_LEN = 12
# 前後にどれだけ文脈を足して語らしくするか
CONTEXT = 2
# 日本語の字だけで出来ていること（記号やゴミを拾わない）
JA_ONLY = re.compile(r"^[ぁ-んァ-ヶ一-龥ー]+$")


def dump(limit, jobs):
    """読み取り結果と正解の対をファイルに落とす。"""
    truth = B.load_truth()
    ids = sorted(truth)
    groups = collections.defaultdict(list)
    for sid in ids:
        groups[truth[sid].get("読みやすさ", "?")].append(sid)
    per = max(1, limit // max(len(groups), 1))
    picked = sorted(sum([g[:per] for g in groups.values()], []))[:limit]

    tasks = [(sid, B.pdf_path(truth[sid]), "auto") for sid in picked]
    out = []
    t0 = time.time()

    def collect(sid, got):
        row = truth[sid]
        for jname, fid in B.TEXT_MAP.items():
            want = row.get(jname)
            if want is None or not str(want).strip():
                continue
            read = (got or {}).get(fid)
            if read is None or not str(read).strip():
                continue
            out.append(dict(sid=sid, field=fid, truth=str(want), read=str(read),
                            legible=row.get("読みやすさ", ""), mode=row.get("mode", "")))

    if jobs > 1:
        import multiprocessing as mp
        with mp.Pool(jobs) as pool:
            for i, (sid, payload, err) in enumerate(
                    pool.imap_unordered(B.run_one, tasks), 1):
                if payload:
                    collect(sid, payload[0])
                if i % 5 == 0:
                    print(f"  {i}/{len(tasks)}（{time.time() - t0:.0f}秒）", flush=True)
    else:
        for i, t in enumerate(tasks, 1):
            sid, payload, err = B.run_one(t)
            if payload:
                collect(sid, payload[0])
            print(f"  {i}/{len(tasks)}", flush=True)

    os.makedirs(os.path.dirname(PAIRS), exist_ok=True)
    with open(PAIRS, "w", encoding="utf-8") as fp:
        json.dump(out, fp, ensure_ascii=False)
    print(f"{len(out)} 対を書き出しました: {PAIRS}（{time.time() - t0:.0f}秒）")


def _vocabulary():
    """本物の語の一覧。直した側がここに載るように切り出せると、語として一般に効く。"""
    import build_word_fixes as W
    return W.vocabulary()


def _span_for(want, j1, j2, vocab):
    """正解の [j1,j2) を含む「語」の範囲を返す。

    直した側が本物の語（「観察」「間食」）になるように広げる。
    語に当たらなければ、前後を CONTEXT 文字だけ足した範囲を返す。
    **語に当たった方が、別の文でも効く一般的な表になる。**
    """
    best = None
    for a in range(max(0, j1 - MAX_LEN), j1 + 1):
        for b in range(j2, min(len(want), j2 + MAX_LEN) + 1):
            w = want[a:b]
            if len(w) < MIN_LEN or w not in vocab:
                continue
            if best is None or (b - a) < (best[1] - best[0]):
                best = (a, b)
    if best:
        return best
    a, b = max(0, j1 - CONTEXT), min(len(want), j2 + CONTEXT)
    return a, b


def _candidates(read, want, vocab):
    """1欄ぶんの読みと正解から、置き換えの候補を取り出す。"""
    sm = difflib.SequenceMatcher(None, read, want)
    out = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag != "replace" or (i2 - i1) != (j2 - j1):
            continue                  # 字数が変わる置き換えは、行のずれの可能性が高い
        a, b = _span_for(want, j1, j2, vocab)
        # 正解側の広げ方に合わせて、読み側も同じだけ広げる
        ia, ib = i1 - (j1 - a), i2 + (b - j2)
        if ia < 0 or ib > len(read):
            continue
        wrong, right = read[ia:ib], want[a:b]
        if wrong == right or len(wrong) != len(right):
            continue
        if not (MIN_LEN <= len(wrong) <= MAX_LEN):
            continue
        if not JA_ONLY.match(wrong) or not JA_ONLY.match(right):
            continue
        out.append((wrong, right, right in vocab))
    return out


def mine(train_ratio, min_count, show):
    with open(PAIRS, encoding="utf-8") as fp:
        pairs = json.load(fp)
    sids = sorted({p["sid"] for p in pairs})
    n_train = max(1, int(len(sids) * train_ratio))
    train_ids = set(sids[:n_train])
    train = [p for p in pairs if p["sid"] in train_ids]
    test = [p for p in pairs if p["sid"] not in train_ids]
    print(f"拾う {len(train_ids)} 通（{len(train)} 欄）/ "
          f"測る {len(sids) - len(train_ids)} 通（{len(test)} 欄）")

    # 本物として通用する語は、誤りとみなしてはいけない。
    # **正解文だけを見てはいけない。** 88通に「左京区」が出てこなかったからといって、
    # 「京都市左京区 → 京都市右京区」を表に入れたら、正しい読みを壊す。
    # 辞書に載っている語（市区町村・傷病名・介護の語）も本物として扱う
    real = "\n".join(p["truth"] for p in pairs)
    vocab_all = _vocabulary()

    vocab = vocab_all
    counts = collections.Counter()
    targets = collections.defaultdict(collections.Counter)
    known = set()
    for p in train:
        for wrong, right, is_word in _candidates(p["read"], p["truth"], vocab):
            counts[wrong] += 1
            targets[wrong][right] += 1
            if is_word:
                known.add(wrong)

    picked = {}
    dropped = collections.Counter()
    for wrong, n in counts.most_common():
        # 直した側が本物の語なら1回でも採る。**語として一般に効く**ため。
        # 語に当たらなかったものは、繰り返し出たものだけ採る
        if n < min_count and wrong not in known:
            dropped["回数が足りず、語にも当たらない"] += 1
            continue
        if wrong in real or wrong in vocab_all:
            dropped["本物の語なので触らない"] += 1
            continue
        # 語の一部が本物の語でも危ない（「京都市左京区」の「左京区」）
        if any(v in wrong for v in vocab_all if len(v) >= 3):
            dropped["本物の語を含む"] += 1
            continue
        cand = targets[wrong]
        if len(cand) > 1 and cand.most_common(1)[0][1] == cand.most_common(2)[1][1]:
            dropped["直す先が決まらない"] += 1
            continue
        picked[wrong] = cand.most_common(1)[0][0]

    print(f"\n拾えた {len(picked)} 語　（捨てた内訳 {dict(dropped)}）")
    if show:
        for w, r in sorted(picked.items(), key=lambda kv: -counts[kv[0]])[:show]:
            mark = "語" if w in known else "　"
            print(f"  {counts[w]:3d} 回 {mark}  {w} → {r}")

    # 測る側（拾っていない通）で効きを見る
    before = after = 0.0
    up = down = 0
    for p in test:
        fixed = p["read"]
        for w, r in picked.items():
            if w in fixed:
                fixed = fixed.replace(w, r)
        b = B.ratio(p["field"], p["truth"], p["read"])
        a = B.ratio(p["field"], p["truth"], fixed)
        before += b; after += a
        if a > b + 1e-9:
            up += 1
        elif a < b - 1e-9:
            down += 1
    if test:
        print(f"\n■ 拾っていない通での効き（{len(test)} 欄）")
        print(f"  文字正解率 {before / len(test) * 100:6.2f}% → "
              f"{after / len(test) * 100:6.2f}%　良化 {up} 件 / 悪化 {down} 件")
    return picked


def write_out(picked, path):
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(picked, fp, ensure_ascii=False, indent=1, sort_keys=True)
    print(f"書き出しました: {path}（{len(picked)} 語）")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("dump", help="読み取り結果と正解の対を落とす")
    d.add_argument("--limit", type=int, default=60)
    d.add_argument("--jobs", type=int, default=6)
    m = sub.add_parser("mine", help="落とした対から誤字表の候補を拾う")
    m.add_argument("--train", type=float, default=0.66, help="拾う通の割合")
    m.add_argument("--min-count", type=int, default=2)
    m.add_argument("--show", type=int, default=40)
    m.add_argument("--out", default=None, help="拾った語の書き出し先(JSON)")
    args = ap.parse_args()

    if args.cmd == "dump":
        dump(args.limit, args.jobs)
    else:
        picked = mine(args.train, args.min_count, args.show)
        if args.out:
            write_out(picked, args.out)


if __name__ == "__main__":
    main()
