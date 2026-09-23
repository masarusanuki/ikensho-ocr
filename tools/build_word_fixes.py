# -*- coding: utf-8 -*-
"""誤字表（dict/word_fixes.json）を作る。Python版とブラウザ版が同じものを読む。

種は3つ。

  1. `dict/care_terms.json`  … 様式の自由記述に出る語（手で書いたもの）
  2. `dict/*.json`           … 傷病名・部位・診療科・感染症の辞書
  3. `dict/ocr_confusions.json` … 形の似た字の組

1文字だけ取り違えた形を機械で作り、**それが本物の語でなければ**表に入れる。
「体重」の体を本に変えた「本重」は語ではないので入れる。
「大工」の大を犬に変えた「犬工」も語ではないので入れる。
一方「未満」の未を末に変えた「末満」は……語ではないので入れる、というように、
**入れてよいかの判断は「本物の語の一覧に無いこと」だけで決める**。

    python3 tools/build_word_fixes.py
    python3 tools/build_word_fixes.py --check   # 最新かどうかだけ見る

**実測データから拾った語を足すときは `--mined` を使う。**
拾う通と測る通を分けること（tools/mine_word_fixes.py の説明を参照）。
"""
import argparse
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DICT = os.path.join(ROOT, "dict")
OUT = os.path.join(DICT, "word_fixes.json")

# 種にする語の最短の長さ。2文字の語を1文字だけ変えると、
# 別の本物の語になりやすい（「入浴」→「人浴」は良いが「大小」→「犬小」は危うい）
MIN_TERM = 3
# 誤りの側がこの長さ未満なら入れない
MIN_WRONG = 3
JA = re.compile(r"^[ぁ-んァ-ヶ一-龥ー]+$")


def load(name):
    path = os.path.join(DICT, name)
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as fp:
        return json.load(fp)


def vocabulary():
    """本物の語の一覧。ここに載っている形は「誤り」として扱わない。"""
    words = set()
    care = load("care_terms.json").get("entries", [])
    words.update(w for w in care if JA.match(w))
    for name in ("diseases.json", "body_sites.json", "departments.json",
                 "infections.json", "clinic_suffix.json", "prefectures.json",
                 "municipalities.json"):
        for e in load(name).get("entries", []):
            n = e.get("name") if isinstance(e, dict) else e
            if n and JA.match(str(n)):
                words.add(str(n))
    return words


def real_text():
    """本物として現れる文字列。様式の印刷文も含めて、誤判定を減らす。"""
    parts = []
    for e in load("boilerplate.json").get("entries", []):
        n = e.get("name") if isinstance(e, dict) else e
        if n:
            parts.append(str(n))
    return "\n".join(parts)


def generate(words, pairs, real):
    """1文字だけ取り違えた形を作る。"""
    fixes = {}
    clash = 0
    for term in sorted(words):
        if len(term) < MIN_TERM:
            continue
        for i, ch in enumerate(term):
            for wrong_ch, right_ch in pairs:
                # 正しい字が term の位置 i にあるとき、誤りの字に置き換えた形を作る
                if ch != right_ch:
                    continue
                wrong = term[:i] + wrong_ch + term[i + 1:]
                if len(wrong) < MIN_WRONG or not JA.match(wrong):
                    continue
                if wrong in words or wrong in real:
                    clash += 1
                    continue            # 本物の語にぶつかる形は作らない
                if wrong in fixes and fixes[wrong] != term:
                    fixes.pop(wrong)    # 2つの語に化けうる形は、どちらにも直せない
                    clash += 1
                    continue
                fixes[wrong] = term
    return fixes, clash


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--mined", default=os.path.join(DICT, "mined_fixes.json"),
                   help="実測から拾った語のJSON（既定 dict/mined_fixes.json）")
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args()

    conf = load("ocr_confusions.json")
    pairs = [tuple(p) for p in conf.get("pairs", [])] + \
            [tuple(p) for p in conf.get("kana_pairs", [])]
    words = vocabulary()
    real = real_text()
    fixes, clash = generate(words, pairs, real)
    made = len(fixes)

    mined = {}
    if args.mined and os.path.exists(args.mined):
        with open(args.mined, encoding="utf-8") as fp:
            raw = json.load(fp)
        mined = raw.get("entries", raw) if isinstance(raw, dict) else {}
        for w, r in mined.items():
            if w in words or w in real:
                continue
            fixes[w] = r

    payload = dict(
        label="OCR の誤字表",
        note=("tools/build_word_fixes.py が作ります。手で書き換えないでください。"
              "種は dict/care_terms.json・dict/ocr_confusions.json と、"
              "実測から拾った語です。"),
        generated=made, mined=len(mined), total=len(fixes),
        entries=dict(sorted(fixes.items())),
    )
    text = json.dumps(payload, ensure_ascii=False, indent=1)
    have = None
    if os.path.exists(args.out):
        with open(args.out, encoding="utf-8") as fp:
            have = fp.read()
    if text == have:
        print("誤字表は最新です。")
        return 0
    if args.check:
        print("誤字表が種と食い違っています。", file=sys.stderr)
        return 1
    with open(args.out, "w", encoding="utf-8") as fp:
        fp.write(text)
    print(f"書き出しました: {args.out}")
    print(f"  種の語 {len(words)} 語 / 字の組 {len(pairs)} 組")
    print(f"  機械で作った {made} 語 / 実測から拾った {len(mined)} 語 / 合計 {len(fixes)} 語")
    print(f"  本物の語にぶつかって捨てた {clash} 語")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
