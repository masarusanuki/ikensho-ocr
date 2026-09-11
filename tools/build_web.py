# -*- coding: utf-8 -*-
"""Web版を配備可能な形に組み立てる。

  dist/web/
    index.html, style.css, js/, vendor/
    data/ikensho.schema.json
    data/templates/*.json, data/templates/refs/*.png
    data/dict/*.json

これをそのまま Web サーバに置けば動作する（サーバ側の処理は不要）。
"""
import argparse
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "python"))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def copytree(src, dst, ignore=None):
    if os.path.isdir(dst):
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=ignore)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "dist", "web"))
    ap.add_argument("--no-ocr-model", action="store_true",
                    help="日本語OCRモデルを同梱しない（tesseract.js に戻る）")
    ap.add_argument("--all-ocr-models", action="store_true",
                    help="入っているモデルをすべて同梱する（比較用。数十MB増える）")
    ap.add_argument("--no-vendor", action="store_true",
                    help="vendor/ を含めない（別途配置する場合）")
    args = ap.parse_args()
    out = os.path.abspath(args.out)
    os.makedirs(out, exist_ok=True)

    for name in ("index.html", "style.css"):
        shutil.copy2(os.path.join(ROOT, "web", name), os.path.join(out, name))
    copytree(os.path.join(ROOT, "web", "js"), os.path.join(out, "js"))
    if not args.no_vendor:
        copytree(os.path.join(ROOT, "web", "vendor"), os.path.join(out, "vendor"))

    data = os.path.join(out, "data")
    os.makedirs(data, exist_ok=True)
    shutil.copy2(os.path.join(ROOT, "schema", "ikensho.schema.json"),
                 os.path.join(data, "ikensho.schema.json"))
    # 管理画面から開発メモを読めるようにする
    for doc in ("DEVNOTES.md", "README.md"):
        src = os.path.join(ROOT, doc)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(data, doc))
    for doc in ("DEVELOPER.md", "INSTALL.md"):
        src = os.path.join(ROOT, "docs", doc)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(data, doc))

    tpl_out = os.path.join(data, "templates")
    os.makedirs(os.path.join(tpl_out, "refs"), exist_ok=True)
    ids = []
    for name in sorted(os.listdir(os.path.join(ROOT, "templates"))):
        if not name.endswith(".json"):
            continue
        tid = name[:-5]
        ids.append(tid)
        shutil.copy2(os.path.join(ROOT, "templates", name), os.path.join(tpl_out, name))
    for name in sorted(os.listdir(os.path.join(ROOT, "templates", "refs"))):
        shutil.copy2(os.path.join(ROOT, "templates", "refs", name),
                     os.path.join(tpl_out, "refs", name))
    blank_src = os.path.join(ROOT, "templates", "blanks")
    if os.path.isdir(blank_src):
        os.makedirs(os.path.join(tpl_out, "blanks"), exist_ok=True)
        for name in sorted(os.listdir(blank_src)):
            shutil.copy2(os.path.join(blank_src, name),
                         os.path.join(tpl_out, "blanks", name))
    with open(os.path.join(tpl_out, "index.json"), "w", encoding="utf-8") as fp:
        json.dump({"templates": ids}, fp, ensure_ascii=False, indent=1)

    # 医療機関一覧は大きいので、都道府県ごとに分けたまま置く（画面から必要な分だけ読む）
    copytree(os.path.join(ROOT, "dict"), os.path.join(data, "dict"))

    # 日本語のOCRモデル（ブラウザで onnxruntime-web に読ませる）。
    # 認識モデルと文字辞書だけを置く。検出モデルは使わない（欄の位置は分かっている）。
    # 大きい server 版はブラウザには重すぎるので入れない。
    ocr_src = os.path.join(ROOT, "models", "ocr")
    browser_models = []
    if os.path.isdir(ocr_src) and not args.no_ocr_model:
        ocr_out = os.path.join(data, "ocr")
        os.makedirs(ocr_out, exist_ok=True)
        for key in sorted(os.listdir(ocr_src)):
            meta_path = os.path.join(ocr_src, key, "model.json")
            if not os.path.exists(meta_path) or "server" in key:
                continue
            with open(meta_path, encoding="utf-8") as fp:
                meta = json.load(fp)
            rec = os.path.join(ocr_src, key, meta.get("rec", ""))
            keys = os.path.join(ocr_src, key, meta.get("keys", ""))
            if not (os.path.exists(rec) and os.path.exists(keys)):
                continue
            os.makedirs(os.path.join(ocr_out, key), exist_ok=True)
            shutil.copy2(rec, os.path.join(ocr_out, key, os.path.basename(rec)))
            shutil.copy2(keys, os.path.join(ocr_out, key, os.path.basename(keys)))
            entry = dict(key=key, note=meta.get("note", ""),
                         rec=os.path.basename(rec), keys=os.path.basename(keys),
                         bytes=os.path.getsize(rec))
            # 文字の位置を見つけるモデル（あればブラウザ版でも使う）
            det = os.path.join(ocr_src, key, meta.get("det", ""))
            if meta.get("det") and os.path.exists(det):
                shutil.copy2(det, os.path.join(ocr_out, key, os.path.basename(det)))
                entry["det"] = os.path.basename(det)
                entry["bytes"] += os.path.getsize(det)
            browser_models.append(entry)
        # 良いと分かっている順に並べる（読み取り側は先頭を使う）
        from ikensho_ocr.ocr import MODEL_PREFERENCE
        order = {k: i for i, k in enumerate(MODEL_PREFERENCE)}
        browser_models.sort(key=lambda m: order.get(m["key"], 99))
        # 既定では**いちばん良いものだけ**を配る（何十MBも配らないため）
        if not args.all_ocr_models:
            for m in browser_models[1:]:
                shutil.rmtree(os.path.join(ocr_out, m["key"]), ignore_errors=True)
            browser_models = browser_models[:1]
        with open(os.path.join(ocr_out, "index.json"), "w", encoding="utf-8") as fp:
            json.dump({"models": browser_models}, fp, ensure_ascii=False, indent=1)

    # ドキュメントは別ページとして生成する（画面内で切り替えない）
    import build_docs_site
    build_docs_site.build(os.path.join(out, "docs"))

    total = sum(os.path.getsize(os.path.join(dp, f))
                for dp, _, fs in os.walk(out) for f in fs)
    print(f"書き出し: {out}")
    print(f"  様式テンプレート: {len(ids)} 種類 ({', '.join(ids)})")
    if browser_models:
        print("  日本語OCRモデル: " + "、".join(
            f"{m['key']}（{m['bytes'] / 1048576:.0f}MB）" for m in browser_models))
    else:
        print("  日本語OCRモデル: なし（python3 tools/fetch_ocr_model.py で取得）")
    print(f"  合計サイズ: {total / 1024 / 1024:.1f} MB")


if __name__ == "__main__":
    main()
