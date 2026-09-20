# -*- coding: utf-8 -*-
"""国立国会図書館の NDLOCR-Lite を取ってくる。

手書きを含む日本語資料向けの OCR で、GPU を必要としない（ONNX Runtime）。
v1.2 から手書き文字の認識を強化したとされており、手書きの意見書に効く見込みがある。

    python3 tools/fetch_ndlocr.py
    python3 tools/fetch_ndlocr.py --list

置き場所は `models/ndlocr/`。読み取り側（`ikensho_ocr.ndlocr`）がそこを見て、
あれば `--engine ndlocr` で使えるようになる。

出どころ: https://github.com/ndl-lab/ndlocr-lite （国立国会図書館 / CC BY 4.0）
**CC BY 4.0 なので、使うときは出典の表示が要る。** 取得時に CREDIT.md を置く。
"""
import argparse
import os
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "models", "ndlocr")
RAW = "https://raw.githubusercontent.com/ndl-lab/ndlocr-lite/master"
UA = ("Mozilla/5.0 (compatible; ikensho-ocr/0.1; "
      "+https://github.com/masarusanuki/ikensho-ocr)")

# 取ってくるもの。モデル・設定・呼び出し用の薄いラッパ
FILES = [
    ("src/model/deim-s-1024x1024.onnx", "文字の場所を見つけるモデル（約38MB）"),
    ("src/model/parseq-ndl-24x384-50-tiny-300epoch-tegaki3-r8data-202604.onnx",
     "文字を読むモデル・中（約36MB）"),
    ("src/config/ndl.yaml", "見つける対象の種類"),
    ("src/config/NDLmoji.yaml", "読める文字の一覧"),
    ("src/deim.py", "場所を見つける部分の呼び出し"),
    ("src/parseq.py", "文字を読む部分の呼び出し"),
    ("LICENCE", "ライセンス（CC BY 4.0）"),
]
# 長い行にも耐える大きいモデル（任意）
EXTRA = [
    ("src/model/parseq-ndl-24x768-100-tiny-153epoch-tegaki3-r8data-202604.onnx",
     "文字を読むモデル・長い行向け（約40MB）"),
    ("src/model/parseq-ndl-24x256-30-tiny-189epoch-tegaki3-r8data-202604.onnx",
     "文字を読むモデル・短い行向け（約34MB）"),
]

CREDIT = """# NDLOCR-Lite について

このフォルダの中身は、国立国会図書館が公開する
[NDLOCR-Lite](https://github.com/ndl-lab/ndlocr-lite) から取得したものです。

- 権利者: 国立国会図書館（National Diet Library, Japan）
- ライセンス: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/deed.ja)
- 取得元: https://github.com/ndl-lab/ndlocr-lite

**CC BY 4.0 は出典の表示を求めます。** このOCRで読み取った結果を使って
成果物を公開する場合は、NDLOCR-Lite を使った旨を表示してください。

`deim.py` と `parseq.py` は取得したそのままのもので、改変していません。
"""


def download(url, dst, label=""):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    tmp = dst + ".part"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=300) as res, open(tmp, "wb") as fp:
        total = int(res.headers.get("Content-Length") or 0)
        got = 0
        while True:
            chunk = res.read(1024 * 256)
            if not chunk:
                break
            fp.write(chunk)
            got += len(chunk)
            if total and os.isatty(1):
                print(f"\r    {label} {got / 1048576:5.1f} / {total / 1048576:.1f} MB",
                      end="", flush=True)
    os.replace(tmp, dst)
    print(f"    {label} {os.path.getsize(dst) / 1048576:5.1f} MB")


def fetch(out_dir=OUT_DIR, extra=False):
    items = FILES + (EXTRA if extra else [])
    for path, note in items:
        dst = os.path.join(out_dir, os.path.basename(path))
        if os.path.exists(dst) and os.path.getsize(dst) > 512:
            print(f"    すでにあります: {os.path.basename(path)}")
            continue
        download(f"{RAW}/{path}", dst, f"{note}")
    with open(os.path.join(out_dir, "CREDIT.md"), "w", encoding="utf-8") as fh:
        fh.write(CREDIT)
    return out_dir


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=OUT_DIR)
    ap.add_argument("--extra", action="store_true",
                    help="長い行向け・短い行向けのモデルも取る")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()
    if args.list:
        print("取得するもの（NDLOCR-Lite / 国立国会図書館 / CC BY 4.0）:")
        for path, note in FILES:
            print(f"  {os.path.basename(path):58s} {note}")
        print("  --extra を付けると、さらに:")
        for path, note in EXTRA:
            print(f"  {os.path.basename(path):58s} {note}")
        return
    print("NDLOCR-Lite を取得します（国立国会図書館 / CC BY 4.0）")
    print(f"  → {fetch(args.out, args.extra)}")
    print("  出典の表示が要ります。CREDIT.md を参照してください。")


if __name__ == "__main__":
    main()
