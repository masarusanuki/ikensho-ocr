# -*- coding: utf-8 -*-
"""オフラインで動く単一HTMLファイルを作る。

CSS・JavaScript・ライブラリ・様式テンプレート・辞書をすべて1ファイルに埋め込む。
出来上がった HTML をダブルクリックすれば、インターネット接続なしで動作する。
"""
import argparse
import base64
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web")
DIST = os.path.join(ROOT, "dist", "web")

MIME = {".json": "application/json", ".md": "text/markdown; charset=utf-8", ".png": "image/png", ".js": "text/javascript",
        ".mjs": "text/javascript", ".gz": "application/gzip",
        ".traineddata": "application/octet-stream"}


def b64(path):
    with open(path, "rb") as fp:
        return base64.b64encode(fp.read()).decode("ascii")


def read(path):
    with open(path, encoding="utf-8") as fp:
        return fp.read()


def collect_assets():
    """埋め込む外部ファイルを (Web上のパス, MIME, base64) で集める。"""
    assets = []
    for base, rel in ((DIST, "data"), (DIST, "vendor")):
        root = os.path.join(base, rel)
        if not os.path.isdir(root):
            continue
        for dirpath, _, names in os.walk(root):
            for n in sorted(names):
                full = os.path.join(dirpath, n)
                web_path = os.path.relpath(full, DIST).replace(os.sep, "/")
                ext = os.path.splitext(n)[1].lower()
                if rel == "vendor" and ext in (".js", ".mjs") and \
                        n not in ("tesseract.worker.min.js", "tesseract-core-simd.wasm.js",
                                  "pdf.worker.min.mjs"):
                    continue    # 本体スクリプトは <script> として直接埋め込む
                assets.append((web_path, MIME.get(ext, "application/octet-stream"), b64(full)))
    return assets


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "dist", "ikensho-standalone.html"))
    args = ap.parse_args()

    if not os.path.isdir(DIST):
        raise SystemExit("先に `python tools/build_web.py` を実行してください。")

    html = read(os.path.join(WEB, "index.html"))
    css = read(os.path.join(WEB, "style.css"))
    app_js = "\n".join(read(os.path.join(WEB, "js", n)) for n in
                       ("engine.js", "dicts.js", "anonymize.js", "pipeline.js",
                        "exporters.js", "review.js", "devnotes.js", "admin.js", "app.js"))
    opencv = read(os.path.join(WEB, "vendor", "opencv.js"))
    tesseract = read(os.path.join(WEB, "vendor", "tesseract.min.js"))
    pdfjs = read(os.path.join(WEB, "vendor", "pdf.min.mjs"))

    assets = collect_assets()
    manifest = [dict(path=p, mime=m, data=d) for p, m, d in assets]

    bootstrap = """
// 埋め込み資産を Blob URL に展開し、通常版と同じパスで参照できるようにする。
(function () {
  const bundle = {};
  for (const a of window.__IKENSHO_ASSETS__) {
    const bin = atob(a.data);
    const buf = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
    bundle[a.path] = URL.createObjectURL(new Blob([buf], { type: a.mime }));
  }
  // tesseract.js は言語データを `${langPath}/jpn.traineddata.gz` で取りにいくため、
  // Blob URL を直接渡せない。取得を横取りして埋め込みデータを返す。
  bundle.__langPath = 'vendor';
  const origFetch = window.fetch.bind(window);
  window.fetch = function (input, init) {
    const url = (typeof input === 'string') ? input : (input && input.url) || '';
    for (const key of Object.keys(bundle)) {
      if (key !== '__langPath' && (url === key || url.endsWith('/' + key) ||
          url.endsWith(key.split('/').pop()) && key.includes('traineddata'))) {
        return origFetch(bundle[key], init);
      }
    }
    return origFetch(input, init);
  };
  window.IKENSHO_BUNDLE = bundle;
  delete window.__IKENSHO_ASSETS__;
})();
"""

    pdf_boot = """
// pdf.js は ES モジュールなので、埋め込んだソースを Blob として import する。
(async function () {
  const src = document.getElementById('pdfjs-src').textContent;
  const url = URL.createObjectURL(new Blob([src], { type: 'text/javascript' }));
  window.pdfjsLib = await import(url);
  window.dispatchEvent(new Event('pdfjs-ready'));
})();
"""

    # index.html を単一ファイル向けに組み替える
    html = html.replace('<link rel="stylesheet" href="style.css">',
                        f"<style>\n{css}\n</style>")
    tail_start = html.index('<script src="vendor/opencv.js" async></script>')
    tail_end = html.index("</body>")
    head = html[:tail_start]

    parts = [head]
    parts.append('<script type="application/json" id="ikensho-assets">')
    parts.append(json.dumps(manifest, ensure_ascii=False, separators=(",", ":")))
    parts.append("</script>")
    parts.append("<script>window.__IKENSHO_ASSETS__ = JSON.parse("
                 "document.getElementById('ikensho-assets').textContent);</script>")
    parts.append(f"<script>{bootstrap}</script>")
    parts.append(f'<script type="text/plain" id="pdfjs-src">{pdfjs}</script>')
    parts.append(f"<script>{opencv}</script>")
    parts.append(f"<script>{tesseract}</script>")
    parts.append(f"<script>{pdf_boot}</script>")
    parts.append(f"<script>{app_js}</script>")
    parts.append("</body>\n</html>\n")

    out = "\n".join(parts)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fp:
        fp.write(out)
    size = os.path.getsize(args.out) / 1024 / 1024
    print(f"書き出し: {args.out}")
    print(f"  埋め込み資産 {len(assets)} 件 / 合計 {size:.1f} MB")
    print("  このファイル1つをブラウザで開けば、オフラインで動作します。")


if __name__ == "__main__":
    main()
