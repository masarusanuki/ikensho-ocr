# -*- coding: utf-8 -*-
"""Markdown のドキュメントから、静的なドキュメントページを生成する。

画面内で切り替えるのではなく、1文書＝1ページとして書き出し、
共通のメニューから行き来できるようにする。
"""
import argparse
import html
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# (出力ファイル名, 元ファイル, メニュー表示名, 説明)
DOCS = [
    ("index.html",     "README.md",          "使い方",       "何ができるか、画面の流れ、出力形式"),
    ("developer.html", "docs/DEVELOPER.md",  "技術者向け",   "構成、全コマンド、新しい様式の追加手順"),
    ("devnotes.html",  "DEVNOTES.md",        "開発メモ",     "設計の経緯、試して駄目だった方法、既知の限界"),
    ("install.html",   "docs/INSTALL.md",    "インストール", "Rocky / Ubuntu / macOS / Windows / Docker"),
]


# --------------------------------------------------------------- Markdown
def inline(s):
    s = html.escape(s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)

    def link(m):
        text, url = m.group(1), m.group(2)
        if url.startswith(("http://", "https://")):
            return f'<a href="{url}" target="_blank" rel="noopener">{text}</a>'
        for out, src, _, _ in DOCS:            # 文書間のリンクを張り替える
            if url.endswith(os.path.basename(src)):
                return f'<a href="{out}">{text}</a>'
        return text
    return re.sub(r"\[([^\]]+)\]\(([^)]+)\)", link, s)


def render(md):
    out, headings = [], []
    in_code = False
    list_type = None
    table = None

    def close_list():
        nonlocal list_type
        if list_type:
            out.append(f"</{list_type}>")
            list_type = None

    def close_table():
        nonlocal table
        if table:
            out.append("<div class='tw'><table><thead><tr>"
                       + "".join(f"<th>{inline(h)}</th>" for h in table["head"])
                       + "</tr></thead><tbody>"
                       + "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>"
                                 for r in table["rows"])
                       + "</tbody></table></div>")
            table = None

    def cells(line):
        return [c.strip() for c in line.strip().strip("|").split("|")]

    for raw in md.split("\n"):
        line = raw.rstrip()
        if line.startswith("```"):
            close_list(); close_table()
            out.append("</code></pre>" if in_code else "<pre><code>")
            in_code = not in_code
            continue
        if in_code:
            out.append(html.escape(raw))
            continue

        if re.match(r"^\|.*\|$", line):
            close_list()
            if table is None:
                table = {"head": cells(line), "rows": []}
                continue
            if re.match(r"^\|[\s:\-|]+\|$", line):
                continue
            table["rows"].append(cells(line))
            continue
        close_table()

        h = re.match(r"^(#{1,4})\s+(.*)$", line)
        if h:
            close_list()
            level = len(h.group(1))
            text = h.group(2)
            hid = "h%d" % len(headings)
            headings.append((level, re.sub(r"[`*]", "", text), hid))
            out.append(f'<h{level} id="{hid}">{inline(text)}</h{level}>')
            continue
        if re.match(r"^---+$", line):
            close_list(); out.append("<hr>"); continue

        ul = re.match(r"^\s*[-*]\s+(.*)$", line)
        ol = re.match(r"^\s*\d+\.\s+(.*)$", line)
        if ul or ol:
            want = "ul" if ul else "ol"
            if list_type != want:
                close_list(); out.append(f"<{want}>"); list_type = want
            body = (ul or ol).group(1)
            body = re.sub(r"^\[( |x|X)\]\s*", lambda m: "☑ " if m.group(1).strip() else "☐ ", body)
            out.append(f"<li>{inline(body)}</li>")
            continue
        close_list()
        if not line.strip():
            continue
        if line.startswith(">"):
            out.append(f"<blockquote>{inline(line.lstrip('> '))}</blockquote>")
            continue
        out.append(f"<p>{inline(line)}</p>")

    close_list(); close_table()
    if in_code:
        out.append("</code></pre>")
    return "\n".join(out), headings


# --------------------------------------------------------------- ページ
STYLE = """
:root{--bg:#f5f6f8;--panel:#fff;--border:#d8dce3;--text:#1d2330;--muted:#6b7280;
 --accent:#1e5aa8;--accent-weak:#e8f0fb}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font-size:14.5px;line-height:1.85;
 font-family:"Hiragino Kaku Gothic ProN","Yu Gothic",Meiryo,system-ui,sans-serif}
header.bar{display:flex;align-items:center;gap:14px;flex-wrap:wrap;padding:10px 18px;
 background:var(--panel);border-bottom:1px solid var(--border);position:sticky;top:0;z-index:20}
header.bar h1{margin:0;font-size:16px}
header.bar .sub{color:var(--muted);font-size:12px}
header.bar .home{margin-left:auto;font-weight:600;color:var(--accent);text-decoration:none}
header.bar .home:hover{text-decoration:underline}
.layout{display:grid;grid-template-columns:250px minmax(0,1fr) 220px;gap:22px;
 max-width:1500px;margin:0 auto;padding:20px 18px 70px;align-items:start}
nav.menu,aside.toc{position:sticky;top:70px;max-height:calc(100vh - 92px);overflow:auto}
nav.menu a{display:block;padding:9px 12px;border-radius:9px;text-decoration:none;
 color:var(--text);margin-bottom:4px;border:1px solid transparent}
nav.menu a .d{display:block;font-size:11.5px;color:var(--muted);font-weight:400}
nav.menu a{font-weight:600;font-size:13.5px}
nav.menu a:hover{background:#eef0f4}
nav.menu a[aria-current]{background:var(--accent-weak);color:var(--accent);
 border-color:#cfd9e8}
nav.menu a[aria-current] .d{color:var(--accent)}
main{background:var(--panel);border:1px solid var(--border);border-radius:12px;
 padding:8px 30px 34px;box-shadow:0 1px 3px rgba(16,24,40,.08);min-width:0}
main h1{font-size:21px;margin:26px 0 10px}
main h2{font-size:17px;margin:30px 0 10px;padding-bottom:6px;
 border-bottom:2px solid var(--accent-weak);color:var(--accent)}
main h3{font-size:15px;margin:22px 0 8px}
main h4{font-size:13.5px;margin:18px 0 6px;color:var(--muted)}
main ul,main ol{padding-left:24px}
main li{margin:3px 0}
main code{background:#eef0f4;border-radius:4px;padding:1px 6px;font-size:12.5px}
main pre{background:#1d2330;color:#e8ecf3;border-radius:9px;padding:14px 16px;
 overflow-x:auto;font-size:12.5px;line-height:1.65}
main pre code{background:none;padding:0;color:inherit;font-size:inherit}
main blockquote{margin:12px 0;padding:10px 16px;background:#fdf3dd;
 border-left:4px solid #e8d08a;border-radius:0 8px 8px 0;color:#6b4a06}
.tw{overflow-x:auto;margin:12px 0}
main table{border-collapse:collapse;width:100%;font-size:13px}
main th,main td{border:1px solid var(--border);padding:6px 10px;text-align:left;
 vertical-align:top}
main th{background:#f7f8fa}
main hr{border:0;border-top:1px solid var(--border);margin:26px 0}
main a{color:var(--accent)}
aside.toc{font-size:12.5px}
aside.toc .t{font-weight:700;color:var(--muted);font-size:11.5px;letter-spacing:.04em;
 margin:6px 0 8px}
aside.toc a{display:block;color:var(--muted);text-decoration:none;padding:3px 8px;
 border-left:2px solid transparent;line-height:1.5;margin-bottom:2px}
aside.toc a:hover{color:var(--accent);border-left-color:var(--accent-weak)}
aside.toc a.l3{padding-left:18px;font-size:12px}
aside.toc a.l4{padding-left:28px;font-size:11.5px}
@media (max-width:1200px){.layout{grid-template-columns:230px minmax(0,1fr)}aside.toc{display:none}}
@media (max-width:820px){.layout{grid-template-columns:1fr}nav.menu{position:static;max-height:none}}
"""


def page(out_name, title, body, headings):
    menu = "".join(
        f'<a href="{o}"{" aria-current=\"page\"" if o == out_name else ""}>'
        f'{html.escape(label)}<span class="d">{html.escape(desc)}</span></a>'
        for o, _, label, desc in DOCS)
    toc = "".join(
        f'<a class="l{lv}" href="#{hid}">{html.escape(text)}</a>'
        for lv, text, hid in headings if 2 <= lv <= 4)
    return f"""<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}｜主治医意見書 読み取り</title>
<style>{STYLE}</style></head><body>
<header class="bar">
  <h1>主治医意見書 読み取り</h1>
  <span class="sub">ドキュメント</span>
  <a class="home" href="../">← アプリに戻る</a>
</header>
<div class="layout">
  <nav class="menu">{menu}</nav>
  <main>{body}</main>
  <aside class="toc"><div class="t">このページの目次</div>{toc}</aside>
</div>
</body></html>"""


def build(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    made = 0
    for out_name, src, label, _ in DOCS:
        path = os.path.join(ROOT, src)
        if not os.path.exists(path):
            print(f"  見つかりません: {src}")
            continue
        with open(path, encoding="utf-8") as fp:
            body, headings = render(fp.read())
        with open(os.path.join(out_dir, out_name), "w", encoding="utf-8") as fp:
            fp.write(page(out_name, label, body, headings))
        print(f"  {out_name:16s} ← {src}  （見出し {len(headings)}）")
        made += 1
    print(f"ドキュメント {made} ページを {out_dir} に生成しました")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "dist", "web", "docs"))
    args = ap.parse_args()
    build(args.out)


if __name__ == "__main__":
    main()
