# -*- coding: utf-8 -*-
"""ブラウザ版の日付欄を正解データと突き合わせる（年・月・日を別々に）。

ブラウザ版は Python 版と**日付の読み方が別実装**（`pipeline.readDate`）なので、
Python 版を測っただけでは分からない。同じ正解データで別に測る。

    python3 tools/test_web_dates.py --limit 8
"""
import argparse
import collections
import http.server
import os
import socketserver
import sys
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
WEB = os.path.join(ROOT, "dist", "web")

from benchmark_dates import JA, PARTS, norm_truth        # noqa: E402
from benchmark_seigo import DATE_MAP, load_truth, pdf_path   # noqa: E402


def start_server(port):
    class H(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=WEB, **kw)

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
    ap.add_argument("--limit", type=int, default=8)
    ap.add_argument("--port", type=int, default=8797)
    ap.add_argument("--detail", type=int, default=12)
    ap.add_argument("--timeout", type=int, default=600000)
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    text_truth = load_truth()["text"]
    docs = sorted(text_truth)[:args.limit]
    paths = [pdf_path(d) for d in docs]
    start_server(args.port)

    stat = {p: collections.Counter() for p in PARTS}
    per_field = collections.defaultdict(lambda: {p: collections.Counter() for p in PARTS})
    misses = []
    errors = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1400, "height": 1000})
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"http://127.0.0.1:{args.port}/", wait_until="domcontentloaded")
        page.wait_for_function(
            "() => document.getElementById('status').textContent.includes('準備ができました')",
            timeout=args.timeout)
        # ラベルの確認は日付に関係ないので切る（そのぶん速い）
        page.uncheck("#opt-labels")

        for i, (doc, path) in enumerate(zip(docs, paths), 1):
            print(f"  [{i}/{len(docs)}] {doc}", flush=True)
            page.set_input_files("#file-input", [path])
            page.wait_for_selector("#filelist li")
            page.click("#btn-run")
            page.wait_for_function(
                "() => { const s = document.getElementById('status').textContent;"
                " return s.includes('完了') || s.includes('エラー'); }",
                timeout=args.timeout)
            got = page.evaluate("""(ids) => {
              const r = window.app.records[window.app.records.length - 1];
              const out = {};
              for (const id of ids) {
                const e = r.fields[id];
                out[id] = e ? { date: e.date || {}, value: e.value, raw: e.raw || '' } : null;
              }
              return out;
            }""", list(DATE_MAP))
            want = text_truth.get(doc) or {}
            for fid, pre in DATE_MAP.items():
                read = (got.get(fid) or {}).get("date") or {}
                for p in PARTS:
                    truth = norm_truth(want.get(f"{pre}_{JA[p]}"))
                    mine = read.get(p)
                    mine_s = "" if mine in (None, "") else str(int(mine))
                    for bucket in (stat[p], per_field[fid][p]):
                        if truth and mine_s == truth:
                            bucket["正解"] += 1
                        elif truth and not mine_s:
                            bucket["抜け"] += 1
                        elif truth:
                            bucket["誤り"] += 1
                        elif mine_s:
                            bucket["余計"] += 1
                        else:
                            bucket["空欄一致"] += 1
                    if truth and mine_s != truth and len(misses) < args.detail:
                        misses.append((doc, fid, JA[p], truth, mine_s or "（抜け）",
                                       (got.get(fid) or {}).get("raw", "")))
            page.click("#btn-clear")
        browser.close()

    print(f"\n■ ブラウザ版・日付の部分ごと（{len(docs)} 通）")
    print(f"  {'':4s} {'記入あり':>8s} {'正解':>6s} {'抜け':>6s} {'誤り':>6s}   {'正解率':>7s}")
    for p in PARTS:
        c = stat[p]
        n = c["正解"] + c["抜け"] + c["誤り"]
        rate = 100 * c["正解"] / n if n else 0.0
        print(f"  {JA[p]:4s} {n:8d} {c['正解']:6d} {c['抜け']:6d} {c['誤り']:6d}   {rate:6.1f}%")
    print("\n  空欄に値を入れた: "
          + "、".join(f"{JA[p]} {stat[p]['余計']}" for p in PARTS))

    print("\n■ 欄ごとの「日」")
    for fid in DATE_MAP:
        c = per_field[fid]["day"]
        n = c["正解"] + c["抜け"] + c["誤り"]
        rate = 100 * c["正解"] / n if n else 0.0
        print(f"  {fid:18s} 記入あり {n:3d}  正解 {c['正解']:3d}  抜け {c['抜け']:3d}"
              f"  誤り {c['誤り']:3d}   {rate:5.1f}%")

    if misses:
        print("\n■ 外した箇所")
        for doc, fid, part, truth, mine, raw in misses:
            print(f"  {doc} {fid:18s} {part} 正解 {truth:>3s} / 読み {mine:>6s}   生読み: {raw}")
    if errors:
        print("\nJavaScript エラー:")
        for e in errors[:10]:
            print("  -", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
