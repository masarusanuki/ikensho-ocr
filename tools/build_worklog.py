# -*- coding: utf-8 -*-
"""作業ログ（WORKLOG.md）の自動生成部分を、git の履歴から書き出す。

WORKLOG.md のうち <!-- AUTO_START --> と <!-- AUTO_END --> に挟まれた範囲だけを
差し替える。指示と対応の対照表など、手で書いた部分はそのまま残る。

    python tools/build_worklog.py            # WORKLOG.md を更新
    python tools/build_worklog.py --check    # 更新が必要かどうかだけ調べる（CI用）
"""
import argparse
import collections
import os
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET = os.path.join(ROOT, "WORKLOG.md")
START, END = "<!-- AUTO_START -->", "<!-- AUTO_END -->"

# 何の作業だったのかが一目で分かるように、置き場所ごとに日本語名をつける
AREAS = [
    ("web/",       "ブラウザ版（確認・編集画面）"),
    ("python/",    "Python版（読み取り本体）"),
    ("tools/",     "生成・検証スクリプト"),
    ("templates/", "様式テンプレート"),
    ("schema/",    "項目定義"),
    ("dict/",      "辞書"),
    ("docs/",      "説明書"),
    ("packaging/", "配布（Docker・インストーラ）"),
    (".github/",   "CI"),
]
CODE_EXT = {".py", ".js", ".html", ".css"}


def git(*args):
    return subprocess.run(["git", "-C", ROOT, *args],
                          capture_output=True, text=True, check=True).stdout


def area_of(path):
    for prefix, name in AREAS:
        if path.startswith(prefix):
            return name
    return "その他（README・設定など）"


def commits():
    """1コミット＝{メタ情報, ファイルごとの増減} にまとめる。"""
    sep = "\x1e"
    raw = git("log", "--reverse", "--numstat",
              f"--pretty=format:{sep}%h|%ad|%s", "--date=format:%Y-%m-%d %H:%M")
    out = []
    for block in raw.split(sep):
        block = block.strip("\n")
        if not block:
            continue
        head, *rest = block.split("\n")
        sha, date, subject = head.split("|", 2)
        files = []
        for line in rest:
            line = line.strip()
            if not line:
                continue
            add, dele, path = line.split("\t")
            # バイナリは - と出るので 0 として扱う
            files.append((int(add) if add != "-" else 0,
                          int(dele) if dele != "-" else 0,
                          path))
        out.append({"sha": sha, "date": date, "subject": subject, "files": files})
    return out


def current_size():
    """今のリポジトリの規模を、置き場所ごとの行数で示す。"""
    rows = collections.Counter()
    counts = collections.Counter()
    for path in git("ls-files").split("\n"):
        if not path or os.path.splitext(path)[1] not in CODE_EXT:
            continue
        full = os.path.join(ROOT, path)
        if not os.path.isfile(full):
            continue
        with open(full, "rb") as fh:
            rows[area_of(path)] += fh.read().count(b"\n") + 1
        counts[area_of(path)] += 1
    return rows, counts


def build():
    cs = commits()
    L = []
    L.append("## 全体")
    L.append("")
    total_add = sum(a for c in cs for a, _, _ in c["files"])
    total_del = sum(d for c in cs for _, d, _ in c["files"])
    L.append(f"- 期間: {cs[0]['date']} 〜 {cs[-1]['date']}")
    L.append(f"- コミット {len(cs)} 件 / 追加 {total_add:,} 行 / 削除 {total_del:,} 行")
    L.append("")

    rows, counts = current_size()
    L.append("### 今のコード量（コメント・空行を含む行数）")
    L.append("")
    L.append("| 置き場所 | ファイル | 行 |")
    L.append("|---|---:|---:|")
    for _, name in AREAS + [("", "その他（README・設定など）")]:
        if counts.get(name):
            L.append(f"| {name} | {counts[name]} | {rows[name]:,} |")
    L.append(f"| **合計** | **{sum(counts.values())}** | **{sum(rows.values()):,}** |")
    L.append("")

    L.append("### どこを何行いじったか（累計）")
    L.append("")
    per = collections.defaultdict(lambda: [0, 0, set()])
    for c in cs:
        for add, dele, path in c["files"]:
            e = per[area_of(path)]
            e[0] += add
            e[1] += dele
            e[2].add(path)
    L.append("| 置き場所 | 追加 | 削除 | 触ったファイル |")
    L.append("|---|---:|---:|---:|")
    for name, (add, dele, files) in sorted(per.items(), key=lambda kv: -kv[1][0]):
        L.append(f"| {name} | {add:,} | {dele:,} | {len(files)} |")
    L.append("")

    L.append("## コミット一覧")
    L.append("")
    L.append("| # | 日時 | 内容 | ファイル | 追加 | 削除 |")
    L.append("|---:|---|---|---:|---:|---:|")
    for i, c in enumerate(cs, 1):
        add = sum(a for a, _, _ in c["files"])
        dele = sum(d for _, d, _ in c["files"])
        L.append(f"| {i} | {c['date']} | {c['subject']} | {len(c['files'])} | "
                 f"{add:,} | {dele:,} |")
    L.append("")

    L.append("## コミットごとの中身")
    L.append("")
    for i, c in enumerate(cs, 1):
        add = sum(a for a, _, _ in c["files"])
        dele = sum(d for _, d, _ in c["files"])
        L.append(f"### {i}. {c['subject']}")
        L.append("")
        L.append(f"`{c['sha']}` {c['date']} — {len(c['files'])} ファイル "
                 f"／ +{add:,} −{dele:,}")
        L.append("")
        ordered = sorted(c["files"], key=lambda f: -(f[0] + f[1]))
        for a, d, path in ordered[:15]:
            L.append(f"- `{path}` +{a} −{d}")
        if len(ordered) > 15:
            rest_a = sum(a for a, _, _ in ordered[15:])
            rest_d = sum(d for _, d, _ in ordered[15:])
            L.append(f"- ほか {len(ordered) - 15} ファイル +{rest_a} −{rest_d}")
        L.append("")
    return "\n".join(L).rstrip() + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="書き換えずに、内容が最新かどうかだけ調べる")
    args = ap.parse_args()

    with open(TARGET, encoding="utf-8") as fh:
        cur = fh.read()
    if START not in cur or END not in cur:
        raise SystemExit(f"{TARGET} に {START} / {END} が見つかりません")
    head, rest = cur.split(START, 1)
    _, tail = rest.split(END, 1)
    new = f"{head}{START}\n\n{build()}\n{END}{tail}"

    if args.check:
        print("最新です" if new == cur else "WORKLOG.md の更新が必要です")
        raise SystemExit(0 if new == cur else 1)
    if new == cur:
        print("WORKLOG.md は最新です")
        return
    with open(TARGET, "w", encoding="utf-8") as fh:
        fh.write(new)
    print(f"WORKLOG.md を更新しました（{TARGET}）")


if __name__ == "__main__":
    main()
