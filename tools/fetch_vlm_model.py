# -*- coding: utf-8 -*-
"""画像を見て文字を読む VLM（GGUF）を取得する。任意機能。

**既定の読み取りには使わない。** PP-OCR のほうが速く、測った精度も高い。
「手書きが崩れていて文字認識モデルが読めない」場合の別手段として、
また両者を同じ正解データで比べるために用意している。

    python3 tools/fetch_vlm_model.py --list
    python3 tools/fetch_vlm_model.py qwen2.5-vl-3b     # 既定
    python3 tools/fetch_vlm_model.py qwen2.5-vl-7b

置き場所は `models/vlm/<名前>/`。本体と mmproj（画像を見る部分）の2つが要る。
読み取り側（`ikensho_ocr.vlm`）がそこを見て、あれば `--engine vlm` で使える。
"""
import argparse
import os
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "models", "vlm")
HF = "https://huggingface.co"
UA = ("Mozilla/5.0 (compatible; ikensho-ocr/0.1; "
      "+https://github.com/masarusanuki/ikensho-ocr)")

# 名前: (説明, 取得元リポジトリ, 本体, mmproj)
CHOICES = {
    "qwen2.5-vl-3b": dict(
        note="Qwen2.5-VL 3B（約2.4GB。日本語の書類に強い。既定）",
        repo="ggml-org/Qwen2.5-VL-3B-Instruct-GGUF",
        model="Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf",
        mmproj="mmproj-Qwen2.5-VL-3B-Instruct-f16.gguf",
    ),
    "qwen2.5-vl-7b": dict(
        note="Qwen2.5-VL 7B（約5.5GB。精度は上だがCPUでは遅い）",
        repo="ggml-org/Qwen2.5-VL-7B-Instruct-GGUF",
        model="Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf",
        mmproj="mmproj-Qwen2.5-VL-7B-Instruct-f16.gguf",
    ),
    "gemma3-4b": dict(
        note="Gemma 3 4B（約2.6GB。比較用）",
        repo="ggml-org/gemma-3-4b-it-GGUF",
        model="gemma-3-4b-it-Q4_K_M.gguf",
        mmproj="mmproj-model-f16.gguf",
    ),
}
DEFAULT = "qwen2.5-vl-3b"


def url_for(repo, name):
    return f"{HF}/{repo}/resolve/main/{urllib.parse.quote(name)}"


def download(url, dst, label=""):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    tmp = dst + ".part"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=300) as res, open(tmp, "wb") as fp:
        total = int(res.headers.get("Content-Length") or 0)
        got = 0
        while True:
            chunk = res.read(1024 * 512)
            if not chunk:
                break
            fp.write(chunk)
            got += len(chunk)
            if total and os.isatty(1):
                print(f"\r    {label} {got / 1048576:6.0f} / {total / 1048576:.0f} MB",
                      end="", flush=True)
    os.replace(tmp, dst)
    print(f"    {label} {os.path.getsize(dst) / 1048576:6.0f} MB 取得しました")


def fetch(key, out_dir=OUT_DIR):
    conf = CHOICES[key]
    base = os.path.join(out_dir, key)
    for part in ("model", "mmproj"):
        name = conf[part]
        dst = os.path.join(base, os.path.basename(name))
        if os.path.exists(dst) and os.path.getsize(dst) > 1024 * 1024:
            print(f"    {part}: すでにあります（{name}）")
            continue
        download(url_for(conf["repo"], name), dst, f"{part}: {name}")
    return base


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("keys", nargs="*", default=None)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--out", default=OUT_DIR)
    args = ap.parse_args()

    if args.list:
        print("選べる VLM:")
        for k, v in CHOICES.items():
            base = os.path.join(args.out, k)
            have = os.path.isdir(base) and any(
                n.endswith(".gguf") and "mmproj" in n.lower()
                for n in os.listdir(base)) if os.path.isdir(base) else False
            print(f"  {k:16s} {'[取得済み] ' if have else '           '}{v['note']}")
        return
    for key in (args.keys or [DEFAULT]):
        if key not in CHOICES:
            raise SystemExit(f"知らないモデルです: {key}（--list で一覧）")
        print(f"{key}: {CHOICES[key]['note']}")
        print(f"  → {fetch(key, args.out)}")


if __name__ == "__main__":
    main()
