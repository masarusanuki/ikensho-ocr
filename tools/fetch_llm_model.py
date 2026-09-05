# -*- coding: utf-8 -*-
"""読み取り候補の提示に使う小型LLM（GGUF）を取得する。任意機能。

この機能は候補を出すだけで、値を自動で確定しない。
まずは辞書照合（編集距離ベース）で十分なことが多いので、
「どうしても読み取りが厳しい様式がある」場合にだけ使う。
"""
import argparse
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS = os.path.join(ROOT, "models")

CHOICES = {
    # 名前: (ファイル名, URL, おおよそのサイズ)
    "qwen2.5-1.5b": (
        "qwen2.5-1.5b-instruct-q4_k_m.gguf",
        "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/"
        "qwen2.5-1.5b-instruct-q4_k_m.gguf",
        "約1.1GB / CPUで1件あたり0.5〜2秒",
    ),
    "qwen2.5-3b": (
        "qwen2.5-3b-instruct-q4_k_m.gguf",
        "https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/"
        "qwen2.5-3b-instruct-q4_k_m.gguf",
        "約2.0GB / 精度は上がるが2〜3倍遅い",
    ),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("model", nargs="?", default="qwen2.5-1.5b", choices=list(CHOICES))
    ap.add_argument("--list", action="store_true", help="選べるモデルを表示する")
    args = ap.parse_args()

    if args.list:
        for k, (fn, _, note) in CHOICES.items():
            print(f"  {k:14s} {note}")
        return

    fn, url, note = CHOICES[args.model]
    os.makedirs(MODELS, exist_ok=True)
    dst = os.path.join(MODELS, fn)
    if os.path.exists(dst):
        print(f"すでにあります: {dst}")
        return
    print(f"取得します: {args.model}（{note}）")

    def hook(block, size, total):
        if total > 0:
            pct = min(100, block * size * 100 // total)
            sys.stderr.write(f"\r  {pct:3d}%")
            sys.stderr.flush()

    urllib.request.urlretrieve(url, dst, hook)
    sys.stderr.write("\n")
    print(f"完了: {dst}")
    print("使い方: ikensho extract ... --llm")


if __name__ == "__main__":
    main()
