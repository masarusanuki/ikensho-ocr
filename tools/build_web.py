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

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def copytree(src, dst, ignore=None):
    if os.path.isdir(dst):
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=ignore)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "dist", "web"))
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

    copytree(os.path.join(ROOT, "dict"), os.path.join(data, "dict"))

    # ドキュメントは別ページとして生成する（画面内で切り替えない）
    import build_docs_site
    build_docs_site.build(os.path.join(out, "docs"))

    total = sum(os.path.getsize(os.path.join(dp, f))
                for dp, _, fs in os.walk(out) for f in fs)
    print(f"書き出し: {out}")
    print(f"  様式テンプレート: {len(ids)} 種類 ({', '.join(ids)})")
    print(f"  合計サイズ: {total / 1024 / 1024:.1f} MB")


if __name__ == "__main__":
    main()
