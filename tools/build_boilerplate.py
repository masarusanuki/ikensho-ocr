# -*- coding: utf-8 -*-
"""様式に印刷されている定型文を抽出する。

OCR がテキスト欄の枠に食い込んで様式自体の文言を読んでしまうことがあるため、
読み取り結果から定型文を除去する目的で使う。
"""
import json
import os
import pdfplumber

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MASTER = os.path.join(ROOT, "master", "主医師意見書.pdf")
OUT = os.path.join(ROOT, "dict", "boilerplate.json")


def main():
    lines = []
    with pdfplumber.open(MASTER) as pdf:
        for page in pdf.pages:
            for ln in page.extract_text_lines(layout=False) or []:
                t = "".join(ln["text"].split())
                t = t.replace("□", "")
                if len(t) >= 4:
                    lines.append(t)
    uniq = sorted(set(lines), key=lambda s: -len(s))
    json.dump(dict(label="様式の印刷文言", entries=[dict(name=t) for t in uniq]),
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"dict/boilerplate.json  {len(uniq)} 行")


if __name__ == "__main__":
    main()
