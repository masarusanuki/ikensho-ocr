# -*- coding: utf-8 -*-
"""項目定義（schema/ikensho.schema.json）だけを作り直す。

`build_master_template.py` でも同じものを書き出すが、あちらは
`master/主医師意見書.pdf` を読んで座標テンプレートも作り直してしまう。
**項目定義だけを直したいとき**は、こちらを使う。

    python3 tools/build_schema.py
    python3 tools/build_schema.py --check   # 最新かどうかだけ調べる（終了コード1なら要更新）
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import form_definition as fd            # noqa: E402

OUT = os.path.join(ROOT, "schema", "ikensho.schema.json")


def build() -> dict:
    return dict(
        version="1.0.0",
        form_name="主治医意見書",
        sections=[dict(id=sid, title=stitle,
                       fields=[{k: v for k, v in f.items() if k != "rect"} for f in flds])
                  for sid, stitle, flds in fd.SECTIONS],
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="書き換えずに差があるかだけ見る")
    args = ap.parse_args()

    want = json.dumps(build(), ensure_ascii=False, indent=1)
    have = None
    if os.path.exists(OUT):
        with open(OUT, encoding="utf-8") as fp:
            have = fp.read()
    if want == have:
        print("項目定義は最新です。")
        return 0
    if args.check:
        print("項目定義が form_definition.py と食い違っています。", file=sys.stderr)
        return 1
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fp:
        fp.write(want)
    n = sum(len(f) for _, _, f in fd.SECTIONS)
    print(f"書き出しました: {OUT}（{n} 項目）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
