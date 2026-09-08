# -*- coding: utf-8 -*-
"""ブラウザ版の OCR 精度を、Python版と同じ正解データで測る。

`bench/ocr_truth.json` の検体を実際のブラウザに読み込ませ、
項目ごとの読み取り値を正解と突き合わせる。
Python 版（`tools/benchmark_ocr.py`）と同じ指標を出すので、
**同じモデルで同じくらい読めているか**を確かめられる。

    python3 tools/test_web_ocr.py
    python3 tools/test_web_ocr.py --raw     # 辞書補正の前（生読み）で比べる
"""
import argparse
import http.server
import json
import os
import socketserver
import sys
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "python"))

from benchmark_ocr import char_accuracy, norm  # noqa: E402


def serve(directory, port):
    class H(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=directory, **kw)

        def log_message(self, *a):
            pass

    class S(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True

    httpd = S(("127.0.0.1", port), H)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--web", default=os.path.join(ROOT, "dist", "web"))
    ap.add_argument("--port", type=int, default=8831)
    ap.add_argument("--raw", action="store_true",
                    help="辞書補正の前（OCRの生読み）で比べる")
    ap.add_argument("--timeout", type=int, default=900000)
    args = ap.parse_args()

    with open(os.path.join(ROOT, "bench", "ocr_truth.json"), encoding="utf-8") as fh:
        truth = json.load(fh)["records"]

    serve(args.web, args.port)
    base = f"http://127.0.0.1:{args.port}/"
    from playwright.sync_api import sync_playwright

    errors = []
    rows = []
    engine = "?"
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1500, "height": 1000})
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append("console: " + m.text)
                if m.type == "error" and "Failed to load resource" not in m.text
                else None)
        page.goto(base, wait_until="domcontentloaded")
        page.wait_for_function(
            "() => document.getElementById('status').textContent.includes('準備ができました')",
            timeout=args.timeout)

        for name in truth:
            path = os.path.join(ROOT, "sample", name)
            page.click("nav.tabs button[data-view='upload']")
            page.set_input_files("#file-input", [path])
            page.wait_for_selector("#filelist li")
            page.click("#btn-run")
            page.wait_for_function(
                "() => { const s = document.getElementById('status').textContent;"
                " return s.includes('完了') || s.includes('エラー'); }",
                timeout=args.timeout)
            got = page.evaluate("""() => {
              const r = window.app.records[window.app.records.length - 1];
              const out = {engine: r.ocrEngine, fields: {}};
              for (const [id, e] of Object.entries(r.fields)) {
                out.fields[id] = {value: e.value === null ? '' : String(e.value),
                                  raw: e.raw || ''};
              }
              return out;
            }""")
            engine = got["engine"]
            for field, expect in truth[name].items():
                info = got["fields"].get(field) or {}
                value = info.get("raw" if args.raw else "value") or ""
                rows.append(dict(file=name, field=field, truth=expect, got=value,
                                 acc=char_accuracy(expect, value)))
            print(f"  {name}: 読み取り完了（{engine}）")
        browser.close()

    filled = [r for r in rows if r["truth"]]
    blank = [r for r in rows if not r["truth"]]
    exact = sum(1 for r in filled if norm(r["truth"]) == norm(r["got"]))
    blank_ok = sum(1 for r in blank if not norm(r["got"]))
    junk = sum(1 for r in blank if len(norm(r["got"])) >= 2)
    print(f"\nブラウザ版（{engine}）"
          f"{'／OCRの生読み' if args.raw else '／辞書補正まで通した値'}")
    print(f"  文字正解率  {sum(r['acc'] for r in rows) / max(len(rows), 1) * 100:5.1f}%"
          f"（{len(rows)} 項目）")
    print(f"  完全一致    {exact / max(len(filled), 1) * 100:5.1f}%"
          f"（記入あり {len(filled)} 項目）")
    print(f"  空欄の判定  {blank_ok / max(len(blank), 1) * 100:5.1f}%"
          f"（空欄 {len(blank)} 項目）／ 拾い読み {junk} 件")

    worst = sorted(rows, key=lambda r: r["acc"])[:10]
    print("\n  読めていない欄:")
    for r in worst:
        if r["acc"] >= 0.999:
            continue
        print(f"    {r['field'][:26]:28s} 正解「{r['truth'][:26]}」")
        print(f"    {'':28s} 読み「{r['got'][:26]}」 {r['acc']:.2f}")

    if errors:
        print("\n  JavaScript エラー:")
        for e in errors[:8]:
            print("   -", e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
