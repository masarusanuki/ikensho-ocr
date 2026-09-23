# -*- coding: utf-8 -*-
"""経過と精度だけをまとめた説明スライド（文字を大きめに）。

`build_pptx.py` は仕組み全体を説明する21枚もの。こちらは
**何をやってきたか／どこまで読めるようになったか**に絞った短い版で、
会議で映すことを想定して字を大きくしてある。

数字は手で書かず、開発メモ（DEVNOTES.md）に載せた実測値と揃えること。

    python3 tools/build_pptx_summary.py
    python3 tools/build_pptx_summary.py --out /path/to/file.pptx
"""
import argparse
import datetime
import os
import subprocess
import sys

from pptx.util import Inches, Pt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

from build_pptx import (ACCENT, FONT, GOOD, INK, MUTED, WARN,   # noqa: E402
                        blank, new_deck, put, table, textbox)

OUT = os.path.join(ROOT, "docs", "主治医意見書読み取り_経過と精度.pptx")

# 映して読める大きさ。本編（build_pptx.py）より一回り大きくしてある
SIZE_TITLE = 38
SIZE_SUB = 20
SIZE_BODY = 22
SIZE_NOTE = 17
SIZE_TABLE = 18


def heading(slide, title, sub=""):
    box = textbox(slide, 0.6, 0.38, 12.1, 1.15)
    tf = box.text_frame
    tf.word_wrap = True
    put(tf, title, size=SIZE_TITLE, bold=True, color=INK, first=True, space_before=0)
    if sub:
        put(tf, sub, size=SIZE_SUB, color=MUTED, space_before=6)
    ln = slide.shapes.add_shape(1, Inches(0.6), Inches(1.72), Inches(12.1),
                                Inches(0.02))
    ln.fill.solid()
    ln.fill.fore_color.rgb = ACCENT
    ln.line.fill.background()
    ln.shadow.inherit = False


def points(slide, items, y=2.05, size=SIZE_BODY):
    # 枠は用紙の中に収める。表の下に置くときは残りの高さしか取らない
    box = textbox(slide, 0.75, y, 11.9, max(1.0, min(4.9, 7.1 - y)))
    tf = box.text_frame
    tf.word_wrap = True
    first = True
    for item in items:
        text, note = item if isinstance(item, tuple) else (item, "")
        put(tf, "・" + text, size=size, bold=True, first=first, space_before=14)
        first = False
        if note:
            put(tf, "　　" + note, size=size - 5, color=MUTED, space_before=3)


def caption(slide, text, y=6.55, color=MUTED, size=SIZE_NOTE):
    box = textbox(slide, 0.75, y, 11.9, 0.7)
    tf = box.text_frame
    tf.word_wrap = True
    put(tf, text, size=size, color=color, first=True, space_before=0)


def commit_span():
    """最初と最後のコミット日、コミット数。"""
    def git(*args):
        return subprocess.run(["git"] + list(args), cwd=ROOT,
                              capture_output=True, text=True).stdout.strip()
    first = git("log", "--reverse", "--format=%ad", "--date=short").split("\n")[0]
    last = git("log", "-1", "--format=%ad", "--date=short")
    count = git("rev-list", "--count", "HEAD")
    return first, last, count


def build(out_path):
    prs = new_deck()
    first_day, last_day, commits = commit_span()

    # 1. 表紙
    s = blank(prs)
    box = textbox(s, 0.9, 2.2, 11.6, 2.6)
    tf = box.text_frame
    tf.word_wrap = True
    put(tf, "主治医意見書の読み取り", size=46, bold=True, first=True, space_before=0)
    put(tf, "これまでの経過と、測った精度", size=28, color=MUTED, space_before=14)
    put(tf, f"{first_day} 〜 {last_day}　コミット {commits} 件",
        size=20, color=MUTED, space_before=20)
    caption(s, "数字はすべて正解データでの実測値です。"
               "どの正解データで測ったかを必ず添えています。", y=5.6)

    # 2. 何を作ったか
    s = blank(prs)
    heading(s, "何を作ったか", "紙の主治医意見書を読み取り、確認して、データにする")
    points(s, [
        ("チェック欄186個は、画像処理で読む",
         "白紙の様式との差分を取ると、枠線もラベルも消えて「書いた印」だけが残る"),
        ("文字欄52個だけ、OCRに任せる",
         "項目107個のうち大半がチェック欄。そこを確実に取るのが精度の要"),
        ("読んだ値は必ず人が確認する前提で作る",
         "確信度で色分けし、要確認だけを絞り込め、該当箇所を原本で拡大できる"),
        ("ブラウザだけで動く（データを外に出さない）",
         "Python版・単一HTMLファイル版も用意。オフラインで動く"),
    ])

    # 3. 経過
    s = blank(prs)
    heading(s, "これまでの経過", "大きな節目だけ")
    table(s, [
        ["時期", "やったこと", "そのときの結果"],
        ["9月上旬", "様式定義・テンプレート・読み取りの土台",
         "チェック欄の検出率 99.5%（正解ラベル無し）"],
        ["9月中旬", "正解データ（100通）をいただき、初めて数値で測れるようになった",
         "チェック欄 95.47%。誤検出が785件あると判明"],
        ["", "判定を書き方ごとに作り直した", "95.47% → 99.08%"],
        ["", "文字欄・日付も測り、弱い欄を個別に直した", "文字 84.3% → 88.4%"],
        ["9月下旬", "新しい検証データ（1,000通）で測り直した",
         "枠単位 89.36%。汚いスキャンで崩れると判明"],
        ["", "出力を整理（JSON・CSV・Markdown）", "答えの読み方を1か所に統一"],
    ], y=2.0, w=12.0, size=SIZE_TABLE, widths=[1.5, 6.0, 4.5])
    caption(s, "「測れるようになってから直す」を守っています。"
               "目で見た比較では、あとで誤りだったと分かったものが複数ありました。")

    # 4. 精度：チェック欄
    s = blank(prs)
    heading(s, "精度① チェック欄", "正解データ100通・□ 18,600枠・□ひとつを1件として数えた")
    table(s, [
        ["", "正解率", "見落とし", "誤検出", "二重線を消せた"],
        ["作り直す前", "95.47 %", "11", "785", "0 / 47"],
        ["いま", "99.08 %", "46", "117", "39 / 47"],
    ], y=2.0, w=12.0, size=22, widths=[2.6, 2.2, 2.2, 2.2, 2.8],
       highlight=lambda r, c, v: r == 2 and c > 0)
    points(s, [
        ("誤検出785件は、すべて枠の中にインクが無かった",
         "1つの広い窓で測っていたため、隣の欄の手書きを拾っていた"),
        ("書き方ごとに、見る場所を分けた",
         "枠の内側／枠の外周（丸囲み）／枠の右下（枠外へのはみ出し）"),
    ], y=4.1)

    # 5. 印の種類ごと
    s = blank(prs)
    heading(s, "精度② 印の書き方ごと", "同じ100通。書き方は13通り")
    table(s, [
        ["印の書き方", "正解率", "件数"],
        ["レ点 / ■ / ×印 / 薄い点 / レ(活字)", "100 %", "1,546"],
        ["チェック ✓", "99.20 %", "249"],
        ["斜め線", "97.96 %", "49"],
        ["塗りつぶし", "97.43 %", "272"],
        ["丸囲み", "97.27 %", "183"],
        ["二重線で訂正", "82.98 %", "47"],
        ["枠外にはみ出した印", "45.61 %", "57"],
    ], y=2.0, w=12.0, size=SIZE_TABLE, widths=[6.0, 3.0, 3.0],
       highlight=lambda r, c, v: r <= 2 and c == 1)
    caption(s, "残る弱点は「枠外にはみ出した印」。枠の中にインクが無く、"
               "外のインクは隣の欄の手書きと見分けが付きません。")

    # 6. 新しい検証データ
    s = blank(prs)
    heading(s, "精度③ 新しい検証データ（1,000通）",
            "Word入力と手書きが混在・64通を読みやすさ4段階から均等に抽出")
    table(s, [
        ["読みやすさ", "チェック欄", "文字欄", "1,000通中"],
        ["活字", "86.5 %", "84.2 %", "350 通"],
        ["標準", "81.6 %", "84.2 %", "204 通"],
        ["達筆（連綿・寝せ字）", "78.1 %", "39.7 %", "227 通"],
        ["汚い（つぶれ・重なり）", "66.4 %", "16.1 %", "219 通"],
    ], y=2.0, w=12.0, size=SIZE_TABLE, widths=[4.2, 2.8, 2.8, 2.2],
       highlight=lambda r, c, v: r == 4)
    points(s, [
        ("崩れているのは「汚い」の1種類に集中している",
         "文字は16.1%で実質読めていない。取り込みの品質がそのまま精度になる"),
        ("枠単位では 89.36%（4,895枠）",
         "100通のデータでの 99.08% とは10ポイント差。しきい値は未調整"),
    ], y=4.5)

    # 7. 数字の読み方
    s = blank(prs)
    heading(s, "数字を見るときの注意", "同じ「正解率」でも、数え方が違うと比べられません")
    table(s, [
        ["数え方", "1件とするもの", "正誤の付け方", "いまの値"],
        ["枠単位", "□ ひとつ", "合っているか（0か1）",
         "99.08 %（100通）\n89.36 %（1,000通）"],
        ["質問単位", "質問ひとつ", "言葉の近さ（0〜1）", "78.13 %"],
        ["文字欄", "欄ひとつ", "言葉の近さ（0〜1）",
         "88.4 %（100通）\n56.12 %（1,000通）"],
    ], y=2.0, w=12.0, size=SIZE_TABLE, widths=[2.2, 2.4, 3.6, 3.8])
    points(s, [
        ("複数選択で3つ中2つ合うと、質問単位では 0.7 が付く",
         "枠単位なら「3枠中2枠正解」。同じ土俵ではないので引き算できない"),
        ("数字は「どの正解データで、何を1件と数えたか」と一緒に出す",
         "当初これを混同し、10ポイントの差を14ポイントと書いていました（訂正済み）"),
    ], y=4.75)

    # 8. 効いたこと
    s = blank(prs)
    heading(s, "効いた工夫", "いずれも実測で確かめたもの")
    table(s, [
        ["やったこと", "変化"],
        ["チェックの判定を、書き方ごとに分けた", "95.47 % → 99.08 %"],
        ["文字を読むモデルを日本語専用に替えた（PP-OCRv4）", "66.7 % → 78.0 %"],
        ["罫線・カッコ・単位を切り落としてから読む", "78.0 % → 84.6 %"],
        ["ふりがな欄で、ひらがなを捨てていた不具合を直した", "0.00 % → 78.1 %"],
        ["テンプレートの記入欄の高さ・中央寄せの取り違えを直した",
         "年齢 12.5 % → 54.2 %ほか"],
        ["カタカナ語の崩れを、並びとして直す（コソ卜口一ル→コソトロール）", "文字 +0.8 ポイント"],
        ["誤字表を機械で作り、1,545語に増やした（市区町村1,914件を含む）",
         "ブラウザ版 96.7 % → 97.1 %"],
    ], y=2.0, w=12.0, size=SIZE_TABLE, widths=[8.4, 3.6],
       highlight=lambda r, c, v: c == 1 and r > 0)
    caption(s, "「ふりがな 0.00%」は、読めていたのに後処理が全部捨てていたもの。"
               "測らなければ気づけませんでした。")

    # 9. 効かなかったこと
    s = blank(prs)
    heading(s, "試して、効かなかったこと", "同じ失敗を繰り返さないために記録しています")
    table(s, [
        ["試したこと", "実測", "どうしたか"],
        ["前処理を強める（二値化・罫線除去）", "いずれも悪化", "控えめな前処理のまま"],
        ["文字を輪郭立てする", "100dpiで 74.0 % → 70.2 %", "切った"],
        ["□をテンプレート無しで見つける", "92.8 %止まり・余計な検出が3〜5倍",
         "組み込まなかった"],
        ["高精度OCRでチェック欄を検算する", "40件を指摘・実際の誤りは0件", "外した"],
        ["LLMで文章を自然な日本語に直す", "3通りの条件すべてで上がらず",
         "既定では使わない"],
    ], y=2.0, w=12.0, size=SIZE_TABLE, widths=[4.6, 4.4, 3.0])
    caption(s, "LLMは、読めない文字から「それらしい日本語」を作ります。"
               "崩れた読みは見れば誤りと分かりますが、作られた文章は見ても分かりません。"
               "そのぶん危ないので、既定では使わず、規則での訂正だけにしています。",
            color=WARN)

    # 9.5 LLMで直せるか
    s = blank(prs)
    heading(s, "「LLMで自然な日本語に直す」を試した結果",
            "正解データで、条件を3通り変えて測りました")
    table(s, [
        ["どの欄を直させたか", "直す前", "直した後", "良くなった", "悪くなった"],
        ["全部", "58.40 %", "57.97 %", "0 件", "1 件"],
        ["確信度0.80以上の欄だけ", "96.10 %", "96.10 %", "0 件", "0 件"],
        ["確信度0.70以上の欄だけ", "92.50 %", "91.61 %", "0 件", "1 件"],
    ], y=2.0, w=12.0, size=SIZE_TABLE, widths=[4.2, 2.0, 2.0, 1.9, 1.9])
    points(s, [
        ("よく読めている欄は、すでに9割以上合っていて直すものが無い", ""),
        ("読めていない欄では、書かれていない言葉を作る",
         "「山要に血じて」→「山要に血圧を測って」。「血圧を測って」は原本にありません"),
        ("規則での訂正は効いた（カタカナ語の崩れなど）",
         "こちらは既定で動いています。ブラウザ版でも同じように直ります"),
    ], y=4.15)

    # 10. これから
    s = blank(prs)
    heading(s, "残っている弱点と、これから")
    points(s, [
        ("読み取りは完全ではない。必ず原本と照らす運用が前提",
         "確認画面はそのために作ってあります"),
        ("つぶれ・重なりの多いスキャンが最大の弱点（1,000通中219通）",
         "文字16.1%。取り込みの品質を上げていただくのが一番効きます"),
        ("枠外にはみ出した印は45.6%",
         "隣の欄の手書きと見分けが付かない。1通単位で見分ける層が要ります"),
        ("正解データは2種類とも合成されたもの",
         "実データでの検証がまだです。ここが次にやるべきことです"),
    ])
    caption(s, f"詳しい実測値と、試して駄目だったことの記録は開発メモ（DEVNOTES.md）にあります。"
               f"　作成 {datetime.date.today().isoformat()}")

    prs.save(out_path)
    return len(prs.slides._sldIdLst)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args()
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    n = build(args.out)
    size = os.path.getsize(args.out) / 1024
    print(f"{n} 枚のスライドを書き出しました: {args.out}（{size:.0f} KB）")


if __name__ == "__main__":
    main()
