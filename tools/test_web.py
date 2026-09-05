# -*- coding: utf-8 -*-
"""ブラウザ版の動作確認（Playwright）。

dist/web を配信して実際にファイルを読み込ませ、確認画面まで到達するかを見る。
"""
import argparse
import http.server
import os
import socketserver
import sys
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "dist", "web")


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
    ap.add_argument("--files", nargs="*", default=[])
    ap.add_argument("--port", type=int, default=8799)
    ap.add_argument("--shots", default=os.path.join(ROOT, "docs", "screenshots"))
    ap.add_argument("--timeout", type=int, default=240000)
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    os.makedirs(args.shots, exist_ok=True)
    start_server(args.port)
    base = f"http://127.0.0.1:{args.port}/"
    errors, logs = [], []

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1500, "height": 1000})
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: logs.append(f"{m.type}: {m.text}")
                if m.type in ("error", "warning") else None)

        page.goto(base, wait_until="domcontentloaded")
        page.wait_for_function(
            "() => document.getElementById('status').textContent.includes('準備ができました')"
            " || document.getElementById('status').classList.contains('err')",
            timeout=args.timeout)
        status = page.text_content("#status")
        print(f"起動: {status}")
        if "err" in (page.get_attribute("#status", "class") or ""):
            print("!! 起動に失敗しました", file=sys.stderr)
            for e in errors[:10]:
                print("   ", e, file=sys.stderr)
            browser.close()
            sys.exit(1)
        page.screenshot(path=os.path.join(args.shots, "01_upload.png"), full_page=True)

        if args.files:
            page.set_input_files("#file-input", args.files)
            page.wait_for_selector("#filelist li")
            print(f"読み込み: {len(args.files)} ファイル")
            page.click("#btn-run")
            page.wait_for_function(
                "() => { const s = document.getElementById('status').textContent;"
                " return s.includes('完了') || s.includes('エラー'); }",
                timeout=args.timeout)
            print("結果:", page.text_content("#status"))
            page.wait_for_timeout(1200)
            page.screenshot(path=os.path.join(args.shots, "02_review.png"), full_page=True)

            summary = page.evaluate("""() => {
              const r = window.app.records[window.app.current];
              if (!r) return null;
              const lv = {high:0, medium:0, low:0};
              let filled = 0;
              for (const id of window.app.schema.order) {
                const e = r.fields[id]; if (!e) continue;
                lv[e.level] = (lv[e.level]||0)+1;
                const v = e.value;
                if (!(v===null||v===undefined||v===''||v===false||(Array.isArray(v)&&!v.length))) filled++;
              }
              return {template: r.templateId, ocr: r.ocrEngine, levels: lv,
                      filled, total: window.app.schema.order.length,
                      warnings: r.warnings, records: window.app.records.length};
            }""")
            print("読み取り結果:", summary)

            # 確認画面で項目を選び、拡大表示を出す
            page.click(".field")
            page.wait_for_timeout(400)
            page.screenshot(path=os.path.join(args.shots, "03_field_focus.png"), full_page=True)

            page.click("nav.tabs button[data-view='records']")
            page.wait_for_timeout(300)
            page.screenshot(path=os.path.join(args.shots, "04_records.png"), full_page=True)

        page.click("nav.tabs button[data-view='admin']")
        page.wait_for_timeout(1200)
        page.screenshot(path=os.path.join(args.shots, "05_admin.png"), full_page=True)

        browser.close()

    if errors:
        print("\nJavaScript エラー:")
        for e in errors[:20]:
            print("  -", e)
        sys.exit(1)
    warn = [l for l in logs if l.startswith("error")]
    if warn:
        print("\nコンソールエラー:")
        for l in warn[:20]:
            print("  -", l)
    print(f"\nスクリーンショット: {args.shots}")


if __name__ == "__main__":
    main()
