# -*- coding: utf-8 -*-
"""日本語に強い OCR 認識モデル（ONNX）を取ってくる。

RapidOCR（onnxruntime）は認識モデルを差し替えられる。既定は中国語向けなので、
**日本語を含むモデル**に替えると精度が上がる。

    python3 tools/fetch_ocr_model.py --list
    python3 tools/fetch_ocr_model.py                 # 既定（ppocrv5_mobile）
    python3 tools/fetch_ocr_model.py ppocrv5_server japan_v4

置き場所は `models/ocr/<名前>/`。読み取り側（`ikensho_ocr.ocr`）が
そこを見て、あれば自動で使う。
"""
import argparse
import json
import os
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "models", "ocr")
HF = "https://huggingface.co"
UA = ("Mozilla/5.0 (compatible; ikensho-ocr/0.1; "
      "+https://github.com/masarusanuki/ikensho-ocr)")

# 名前: (説明, 認識モデル, 文字辞書, 追加で取るもの)
CHOICES = {
    "ppocrv5_mobile": dict(
        note="PP-OCRv5 mobile（日本語・中国語・英語を1つで。約16MB。既定）",
        rec=("bukuroo/PPOCRv5-ONNX", "ppocrv5-mobile-rec.onnx"),
        keys=("bukuroo/PPOCRv5-ONNX", "ppocrv5_dict.txt"),
        det=("bukuroo/PPOCRv5-ONNX", "ppocrv5-mobile-det.onnx"),
    ),
    "ppocrv5_server": dict(
        note="PP-OCRv5 server（同じ系列の大きい版。約85MB・遅いが精度は上）",
        rec=("bukuroo/PPOCRv5-ONNX", "ppocrv5-server-rec.onnx"),
        keys=("bukuroo/PPOCRv5-ONNX", "ppocrv5_dict.txt"),
        det=("bukuroo/PPOCRv5-ONNX", "ppocrv5-server-det.onnx"),
    ),
    "japan_v4": dict(
        note="PP-OCRv4 日本語専用（日本語だけを学習。約11MB）",
        rec=("cycloneboy/japan_PP-OCRv4_rec_infer", "model.onnx"),
        keys=("cycloneboy/japan_PP-OCRv4_rec_infer", "japan_dict.txt"),
        # 文字の位置を見つけるモデル。Python 版（rapidocr 同梱）と同じもの。
        # ブラウザ版でも「どこに字があるか」を先に見つけるために使う
        det=("SWHL/RapidOCR", "PP-OCRv4/ch_PP-OCRv4_det_infer.onnx"),
    ),
    "japan_v3": dict(
        note="PP-OCRv3 日本語専用（古い版。比較用）",
        rec=("tobiichioriguchi/japan_PP-OCRv3_mobile_rec_onnx", "inference.onnx"),
        keys=("cycloneboy/japan_PP-OCRv4_rec_infer", "japan_dict.txt"),
    ),
}
DEFAULT = "ppocrv5_mobile"


def url_for(repo, name):
    return f"{HF}/{repo}/resolve/main/{urllib.parse.quote(name)}"


def download(url, dst, label=""):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    tmp = dst + ".part"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=180) as res, open(tmp, "wb") as fp:
        total = int(res.headers.get("Content-Length") or 0)
        got = 0
        while True:
            chunk = res.read(1024 * 256)
            if not chunk:
                break
            fp.write(chunk)
            got += len(chunk)
            # 端末に出しているときだけ進捗を上書き表示する（ログでは邪魔になる）
            if total and os.isatty(1):
                print(f"\r    {label} {got / 1048576:5.1f} / {total / 1048576:.1f} MB",
                      end="", flush=True)
    os.replace(tmp, dst)
    print(f"    {label} {os.path.getsize(dst) / 1048576:5.1f} MB 取得しました")


def fetch(key, out_dir=OUT_DIR, verbose=True):
    conf = CHOICES[key]
    base = os.path.join(out_dir, key)
    got = {}
    for part in ("rec", "keys", "det"):
        if part not in conf:
            continue
        repo, name = conf[part]
        # 置き場所は名前だけにする（取得元がフォルダ付きの場合があるため）
        dst = os.path.join(base, os.path.basename(name))
        got[part] = dst
        if os.path.exists(dst) and os.path.getsize(dst) > 1024:
            if verbose:
                print(f"    {part}: すでにあります（{name}）")
            continue
        download(url_for(repo, name), dst, f"{part}: {name}")
    # 読み取り側が見る設定ファイル
    meta = dict(key=key, note=conf["note"],
                rec=os.path.basename(got["rec"]),
                keys=os.path.basename(got["keys"]),
                det=os.path.basename(got["det"]) if "det" in got else "")
    with open(os.path.join(base, "model.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=1)
    return base


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("keys", nargs="*", default=None)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--out", default=OUT_DIR)
    args = ap.parse_args()

    if args.list:
        print("選べる認識モデル:")
        for k, v in CHOICES.items():
            base = os.path.join(args.out, k)
            have = os.path.exists(os.path.join(base, "model.json"))
            print(f"  {k:16s} {'[取得済み] ' if have else '           '}{v['note']}")
        return
    keys = args.keys or [DEFAULT]
    for key in keys:
        if key not in CHOICES:
            raise SystemExit(f"知らないモデルです: {key}（--list で一覧）")
        print(f"{key}: {CHOICES[key]['note']}")
        base = fetch(key, args.out)
        print(f"  → {base}")


if __name__ == "__main__":
    main()
