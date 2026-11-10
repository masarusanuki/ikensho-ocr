# -*- coding: utf-8 -*-
"""開発メモの changelog を、git の履歴から書き出す。

**GitHub に上げたコミットだけ**を並べる（手元にしか無いものは出さない）。
開発メモ（DEVNOTES.md）の <!-- CHANGELOG_START --> と <!-- CHANGELOG_END -->
に挟まれた範囲だけを差し替える。

    python3 tools/build_changelog.py
    python3 tools/build_changelog.py --check   # 最新かどうかだけ調べる（終了コード1なら要更新）
"""
import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET = os.path.join(ROOT, "DEVNOTES.md")
START, END = "<!-- CHANGELOG_START -->", "<!-- CHANGELOG_END -->"
REPO = "https://github.com/masarusanuki/ikensho-ocr"
# 何を触ったかが一目で分かるように、置き場所ごとに日本語名をつける
AREAS = [
    ("python/", "読み取り"),
    ("web/", "ブラウザ版"),
    ("tools/", "道具"),
    ("templates/", "様式"),
    ("dict/", "辞書"),
    ("schema/", "項目定義"),
    ("docs/", "説明"),
    ("packaging/", "配布"),
    (".github/", "ビルド"),
]


def git(*args):
    return subprocess.run(["git", "-C", ROOT, *args],
                          capture_output=True, text=True).stdout


def pushed_commits():
    """**上流に上がっているコミットだけ**を、新しい順に返す。"""
    upstream = git("rev-parse", "--abbrev-ref", "--symbolic-full-name",
                   "@{upstream}").strip()
    if not upstream:
        upstream = "origin/main"
    raw = git("log", upstream, "--no-merges",
              "--pretty=format:%H\x1f%ad\x1f%s\x1e", "--date=short")
    out = []
    for rec in raw.split("\x1e"):
        rec = rec.strip("\n")
        if not rec:
            continue
        sha, date, subject = rec.split("\x1f")
        files = git("show", "--name-only", "--pretty=format:", sha).split()
        areas = []
        for prefix, name in AREAS:
            if any(f.startswith(prefix) for f in files) and name not in areas:
                areas.append(name)
        out.append(dict(sha=sha, date=date, subject=subject,
                        areas=areas, files=len(files)))
    return out


def render(commits):
    lines = [START, "",
             "**この表は `tools/build_changelog.py` が git の履歴から作ります。"
             "手で書き換えないでください。**",
             "GitHub に上がっているものだけを載せています。", "",
             f"全 {len(commits)} 件。新しいものが上です。", "",
             "| 日付 | 変えたこと | 触ったところ | |",
             "|---|---|---|---|"]
    for c in commits:
        area = "・".join(c["areas"]) or "—"
        link = f"[{c['sha'][:7]}]({REPO}/commit/{c['sha']})"
        subject = c["subject"].replace("|", "｜")
        lines.append(f"| {c['date']} | {subject} | {area} | {link} |")
    lines += ["", END]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    with open(TARGET, encoding="utf-8") as fp:
        text = fp.read()
    if START not in text or END not in text:
        print(f"{TARGET} に {START} / {END} がありません。", file=sys.stderr)
        return 1
    head, rest = text.split(START, 1)
    _, tail = rest.split(END, 1)
    new = head + render(pushed_commits()) + tail
    if new == text:
        print("changelog は最新です。")
        return 0
    if args.check:
        print("changelog の更新が必要です。", file=sys.stderr)
        return 1
    with open(TARGET, "w", encoding="utf-8") as fp:
        fp.write(new)
    print(f"changelog を更新しました: {TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
