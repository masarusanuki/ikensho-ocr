# -*- coding: utf-8 -*-
"""動作確認用サンプルの一覧ページを作る。

サムネイル付きで、1件ずつのプレビュー／ダウンロードと、
種類ごと・全件のまとめてダウンロード（zip）を用意する。
"""
import argparse
import html
import os
import zipfile

CATEGORIES = [
    ("official", "公式様式（厚生労働省 標準様式・スキャン）", lambda f: f.startswith("ikensho_")),
    ("word", "サンプル様式（印刷・スキャン）", lambda f: "word-scan" in f),
    ("handscan", "サンプル様式（手書き・スキャン）", lambda f: "hand-scan" in f),
    ("hand", "サンプル様式（手書き）", lambda f: True),
]
STARTER = 8      # お試しセットに入れる件数（種類ごとに均等）


def categorize(files):
    groups = {key: [] for key, _, _ in CATEGORIES}
    for f in files:
        for key, _, test in CATEGORIES:
            if test(f):
                groups[key].append(f)
                break
    return groups


def make_zip(path, base, names):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as z:
        for n in names:
            z.write(os.path.join(base, n), n)
    return os.path.getsize(path)


def human(n):
    return f"{n / 1024 / 1024:.1f} MB" if n >= 1024 * 1024 else f"{n / 1024:.0f} KB"


def build(directory):
    files = sorted(f for f in os.listdir(directory) if f.lower().endswith(".pdf"))
    if not files:
        raise SystemExit(f"PDF が見つかりません: {directory}")
    groups = categorize(files)

    zips = {}
    print("まとめてダウンロード用の zip を作成します")
    for key, label, _ in CATEGORIES:
        names = groups[key]
        if not names:
            continue
        name = f"samples_{key}.zip"
        size = make_zip(os.path.join(directory, name), directory, names)
        zips[key] = (name, size, len(names))
        print(f"  {name}  {len(names)}件  {human(size)}")

    starter = []
    for key, _, _ in CATEGORIES:
        starter += groups[key][:max(1, STARTER // max(1, len(CATEGORIES)))]
    if starter:
        size = make_zip(os.path.join(directory, "samples_starter.zip"), directory, starter)
        zips["starter"] = ("samples_starter.zip", size, len(starter))
        print(f"  samples_starter.zip  {len(starter)}件  {human(size)}")

    size = make_zip(os.path.join(directory, "samples_all.zip"), directory, files)
    zips["all"] = ("samples_all.zip", size, len(files))
    print(f"  samples_all.zip  {len(files)}件  {human(size)}")

    has_thumbs = os.path.isdir(os.path.join(directory, "thumbs"))
    sections = []
    for key, label, _ in CATEGORIES:
        names = groups[key]
        if not names:
            continue
        zn = zips.get(key)
        head = (f'<h2>{html.escape(label)}<span class="n">{len(names)}件</span>'
                + (f'<a class="zip" href="{zn[0]}" download>まとめてダウンロード '
                   f'（{human(zn[1])}）</a>' if zn else '') + '</h2>')
        cards = []
        for f in names:
            stem = f[:-4]
            thumb = (f'<img loading="lazy" src="thumbs/{html.escape(stem)}.jpg" alt="">'
                     if has_thumbs else '<div class="noimg">PDF</div>')
            size = human(os.path.getsize(os.path.join(directory, f)))
            cards.append(
                f'<figure class="card">'
                f'<a class="thumb" href="{html.escape(f)}" target="_blank" rel="noopener"'
                f' title="別のタブで開いて内容を確認します">{thumb}</a>'
                f'<figcaption><span class="name" title="{html.escape(f)}">'
                f'{html.escape(stem)}</span><span class="size">{size}</span></figcaption>'
                f'<div class="acts">'
                f'<a href="{html.escape(f)}" target="_blank" rel="noopener">プレビュー</a>'
                f'<a href="{html.escape(f)}" download>ダウンロード</a>'
                f'</div></figure>')
        sections.append(f'<section>{head}<div class="grid">{"".join(cards)}</div></section>')

    starter_zip = zips.get("starter")
    all_zip = zips["all"]
    page = f'''<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>動作確認用サンプル</title>
<style>
body{{font-family:"Hiragino Kaku Gothic ProN","Yu Gothic",Meiryo,system-ui,sans-serif;
 margin:0;background:#f5f6f8;color:#1d2330;font-size:14px;line-height:1.7}}
main{{max-width:1300px;margin:0 auto;padding:22px 18px 60px}}
h1{{font-size:19px;margin:0 0 6px}}
.lead{{color:#6b7280;font-size:13px;margin:0 0 16px}}
.back{{display:inline-block;margin-bottom:14px;font-weight:600;color:#1e5aa8;text-decoration:none}}
.back:hover{{text-decoration:underline}}
.note{{background:#fdf3dd;border:1px solid #e8d08a;color:#6b4a06;border-radius:9px;
 padding:10px 14px;font-size:13px;margin-bottom:16px}}
.bulk{{background:#fff;border:1px solid #d8dce3;border-radius:12px;padding:14px 18px;
 margin-bottom:18px;box-shadow:0 1px 3px rgba(16,24,40,.08);
 display:flex;gap:10px;flex-wrap:wrap;align-items:center}}
.bulk b{{font-size:13px}}
.btn{{display:inline-block;border:1px solid #d8dce3;background:#fff;border-radius:8px;
 padding:8px 14px;font-weight:600;color:#1d2330;text-decoration:none;font-size:13px}}
.btn:hover{{background:#f0f2f5}}
.btn.primary{{background:#1e5aa8;border-color:#1e5aa8;color:#fff}}
.btn.primary:hover{{background:#17498a}}
section{{background:#fff;border:1px solid #d8dce3;border-radius:12px;padding:14px 18px 18px;
 margin-bottom:16px;box-shadow:0 1px 3px rgba(16,24,40,.08)}}
h2{{font-size:14px;margin:0 0 12px;color:#1e5aa8;display:flex;align-items:center;
 gap:10px;flex-wrap:wrap}}
.n{{color:#6b7280;font-weight:400;font-size:12px}}
.zip{{margin-left:auto;font-size:12.5px;font-weight:600;color:#1e5aa8;text-decoration:none;
 border:1px solid #cfd9e8;background:#e8f0fb;border-radius:999px;padding:3px 12px}}
.zip:hover{{background:#dbe8fa}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:14px}}
.card{{margin:0;border:1px solid #e3e6eb;border-radius:9px;overflow:hidden;background:#fff}}
.card .thumb{{display:block;background:#eef0f4;line-height:0}}
.card img{{width:100%;height:auto;display:block}}
.noimg{{height:150px;display:grid;place-items:center;color:#9aa1ad;font-size:12px}}
figcaption{{display:flex;justify-content:space-between;gap:6px;padding:6px 8px 2px;
 font-size:11.5px}}
.name{{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:600}}
.size{{color:#6b7280;white-space:nowrap}}
.acts{{display:flex;gap:6px;padding:4px 8px 8px}}
.acts a{{flex:1;text-align:center;font-size:11.5px;padding:4px 0;border-radius:6px;
 text-decoration:none;border:1px solid #d8dce3;color:#1e5aa8;background:#fff}}
.acts a:hover{{background:#eef4fc}}
.acts a[download]{{background:#1e5aa8;border-color:#1e5aa8;color:#fff}}
.acts a[download]:hover{{background:#17498a}}
</style></head>
<body><main>
<a class="back" href="../">← 読み取り画面に戻る</a>
<h1>動作確認用サンプル</h1>
<p class="lead">主治医意見書の読み取りを試すためのファイルです（全{len(files)}件）。
サムネイルまたは「プレビュー」で内容を確認し、「ダウンロード」で取得して読み取り画面に読み込ませてください。</p>
<div class="note">これらは動作確認のために生成したもので、実在の人物の情報ではありません。</div>
<div class="bulk">
  <b>まとめてダウンロード</b>
  {f'<a class="btn primary" href="{starter_zip[0]}" download>お試しセット（{starter_zip[2]}件・{human(starter_zip[1])}）</a>' if starter_zip else ''}
  <a class="btn" href="{all_zip[0]}" download>全{all_zip[2]}件（{human(all_zip[1])}）</a>
  <span class="n">種類ごとのまとめは各見出しの右側にあります</span>
</div>
{''.join(sections)}
</main></body></html>'''
    with open(os.path.join(directory, "index.html"), "w", encoding="utf-8") as fp:
        fp.write(page)
    print(f"一覧ページを作成: {os.path.join(directory, 'index.html')}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("directory", help="サンプルPDFを置いたディレクトリ")
    args = ap.parse_args()
    build(args.directory)


if __name__ == "__main__":
    main()
