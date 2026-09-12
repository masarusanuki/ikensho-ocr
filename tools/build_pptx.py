# -*- coding: utf-8 -*-
"""説明用のスライド（PPTX）を作る。

数字は手で書かず、できる限り実際のファイルから読む。
（項目定義・医療機関一覧・モデル比較の表・GitHub の Issue 数）

    python3 tools/build_pptx.py
    python3 tools/build_pptx.py --out /path/to/file.pptx
"""
import argparse
import datetime
import json
import os
import re
import subprocess

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.util import Emu, Inches, Pt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "主治医意見書読み取り_概要.pptx")

FONT = "Yu Gothic"
INK = RGBColor(0x1B, 0x1F, 0x24)
MUTED = RGBColor(0x5B, 0x63, 0x6E)
ACCENT = RGBColor(0x1E, 0x5A, 0xA8)
GOOD = RGBColor(0x1A, 0x7F, 0x4B)
WARN = RGBColor(0xB0, 0x4A, 0x0A)
LINE = RGBColor(0xD5, 0xD9, 0xDF)
BAND = RGBColor(0xF2, 0xF5, 0xF9)

COPYRIGHT = ("Masaru Sanuki, University of Tsukuba & "
             "Department of Biomedical Informatics, University of Tsukuba Hospital")


# ------------------------------------------------------------ 実データの読み込み
def schema_counts():
    path = os.path.join(ROOT, "schema", "ikensho.schema.json")
    with open(path, encoding="utf-8") as fh:
        sc = json.load(fh)
    fields = [f for s in sc["sections"] for f in s["fields"]]
    tpl = os.path.join(ROOT, "templates", "official_v1.json")
    with open(tpl, encoding="utf-8") as fh:
        t = json.load(fh)
    boxes = sum(len(p["boxes"]) for p in t["pages"])
    return len(fields), boxes


def hospital_counts():
    path = os.path.join(ROOT, "dict", "hospitals", "index.json")
    try:
        with open(path, encoding="utf-8") as fh:
            idx = json.load(fh)
    except Exception:
        return 0, 0, ""
    prefs = idx.get("prefectures", [])
    return (len(prefs), sum(p.get("count", 0) for p in prefs),
            (idx.get("updated") or "")[:10])


def _md_table(marker):
    """docs/DEVELOPER.md の印で囲まれた表を読む。"""
    path = os.path.join(ROOT, "docs", "DEVELOPER.md")
    with open(path, encoding="utf-8") as fh:
        md = fh.read()
    m = re.search(f"<!-- {marker}_START -->(.*?)<!-- {marker}_END -->", md, re.S)
    if not m:
        return []
    rows = []
    for line in m.group(1).strip().split("\n"):
        if not line.startswith("|") or set(line) <= set("|-: "):
            continue
        rows.append([c.strip() for c in line.strip().strip("|").split("|")])
    return rows


def model_bench():
    return _md_table("MODEL_BENCH")


def ocr_bench():
    return _md_table("OCR_BENCH")


def issue_counts():
    try:
        out = subprocess.run(
            ["gh", "issue", "list", "--state", "all", "--limit", "200",
             "--json", "state"],
            capture_output=True, text=True, cwd=ROOT, timeout=60)
        data = json.loads(out.stdout or "[]")
        closed = sum(1 for d in data if d.get("state") == "CLOSED")
        return len(data), len(data) - closed
    except Exception:
        return 0, 0


# ------------------------------------------------------------ 描画の道具
def new_deck():
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    return prs


def blank(prs):
    return prs.slides.add_slide(prs.slide_layouts[6])


def textbox(slide, x, y, w, h):
    return slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))


def put(tf, text, size=18, bold=False, color=INK, space_before=6,
        align=PP_ALIGN.LEFT, first=False):
    p = tf.paragraphs[0] if first else tf.add_paragraph()
    p.alignment = align
    p.space_before = Pt(space_before)
    run = p.add_run()
    run.text = text
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color
    run.font.name = FONT
    return p


def heading(slide, title, sub=""):
    box = textbox(slide, 0.6, 0.42, 12.1, 1.0)
    tf = box.text_frame
    tf.word_wrap = True
    put(tf, title, size=30, bold=True, color=INK, first=True, space_before=0)
    if sub:
        put(tf, sub, size=14, color=MUTED, space_before=4)
    ln = slide.shapes.add_shape(1, Inches(0.6), Inches(1.52), Inches(12.1), Emu(11430))
    ln.fill.solid()
    ln.fill.fore_color.rgb = ACCENT
    ln.line.fill.background()
    ln.shadow.inherit = False


def bullets(slide, items, x=0.75, y=1.85, w=11.9, size=17):
    box = textbox(slide, x, y, w, 5.0)
    tf = box.text_frame
    tf.word_wrap = True
    first = True
    for item in items:
        if isinstance(item, tuple):
            text, note = item
        else:
            text, note = item, ""
        put(tf, "・" + text, size=size, bold=True, first=first, space_before=10)
        first = False
        if note:
            put(tf, "　　" + note, size=size - 3, color=MUTED, space_before=2)


def table(slide, rows, x=0.75, y=1.9, w=11.8, h=None, size=13, widths=None,
          highlight=None):
    n_rows, n_cols = len(rows), len(rows[0])
    h = h or min(0.42 * n_rows + 0.1, 5.0)
    shape = slide.shapes.add_table(n_rows, n_cols, Inches(x), Inches(y),
                                   Inches(w), Inches(h))
    tbl = shape.table
    if widths:
        total = sum(widths)
        for i, ww in enumerate(widths):
            tbl.columns[i].width = Emu(int(Inches(w) * ww / total))
    for r, row in enumerate(rows):
        for c, val in enumerate(row):
            cell = tbl.cell(r, c)
            cell.text = ""
            para = cell.text_frame.paragraphs[0]
            run = para.add_run()
            run.text = str(val)
            run.font.size = Pt(size)
            run.font.name = FONT
            run.font.bold = (r == 0)
            color = INK
            if r == 0:
                color = RGBColor(0xFF, 0xFF, 0xFF)
            elif highlight and highlight(r, c, str(val)):
                color = GOOD
            run.font.color.rgb = color
            cell.fill.solid()
            cell.fill.fore_color.rgb = (ACCENT if r == 0
                                        else (BAND if r % 2 == 0
                                              else RGBColor(0xFF, 0xFF, 0xFF)))
            cell.margin_top = Pt(3)
            cell.margin_bottom = Pt(3)
    return tbl


def note(slide, text, y=6.6, color=MUTED, size=13):
    box = textbox(slide, 0.75, y, 11.9, 0.6)
    tf = box.text_frame
    tf.word_wrap = True
    put(tf, text, size=size, color=color, first=True, space_before=0)


def footer(prs):
    for i, slide in enumerate(prs.slides, start=1):
        if i == 1:
            continue
        box = textbox(slide, 0.6, 6.95, 12.1, 0.4)
        tf = box.text_frame
        p = tf.paragraphs[0]
        p.alignment = PP_ALIGN.RIGHT
        run = p.add_run()
        run.text = f"主治医意見書 読み取り　|　{i}"
        run.font.size = Pt(10)
        run.font.color.rgb = MUTED
        run.font.name = FONT


# ------------------------------------------------------------ スライド
def build(out_path):
    fields, boxes = schema_counts()
    n_pref, n_hosp, hosp_updated = hospital_counts()
    models = model_bench()
    n_issue, n_open = issue_counts()
    today = datetime.date.today().strftime("%Y年%-m月%-d日")

    prs = new_deck()

    # 1. 表紙
    s = blank(prs)
    bg = s.shapes.add_shape(1, 0, 0, prs.slide_width, Inches(2.9))
    bg.fill.solid()
    bg.fill.fore_color.rgb = ACCENT
    bg.line.fill.background()
    bg.shadow.inherit = False
    box = textbox(s, 0.9, 0.95, 11.6, 1.8)
    tf = box.text_frame
    put(tf, "主治医意見書 読み取りアプリ", size=40, bold=True,
        color=RGBColor(0xFF, 0xFF, 0xFF), first=True, space_before=0)
    put(tf, "介護認定の主治医意見書を読み取り、確認・編集して JSON / CSV にする",
        size=17, color=RGBColor(0xDC, 0xE6, 0xF5))
    box = textbox(s, 0.9, 3.4, 11.6, 2.4)
    tf = box.text_frame
    tf.word_wrap = True
    put(tf, f"項目 {fields} 項目 ／ チェック欄 {boxes} 箇所 ／ 検証 250 検体",
        size=18, bold=True, first=True, space_before=0)
    put(tf, "端末内で処理し、患者情報を外部に送信しません", size=15, color=MUTED)
    put(tf, "", size=8)
    put(tf, COPYRIGHT, size=13, color=MUTED)
    put(tf, today, size=13, color=MUTED)

    # 2. 何ができるか
    s = blank(prs)
    heading(s, "できること", "読み取り → 確認・編集 → 保存")
    bullets(s, [
        ("2ページのPDF・画像を、1件でも複数件でも読み取る",
         "スマートフォンやタブレットで1ページずつ撮った写真にも対応（ページの並びを自動で判定）"),
        (f"チェック欄 {boxes} 箇所は OCR を使わずに判定する",
         "白紙様式との差分で見るため、手書き・印刷・スキャンのいずれでも安定する"),
        ("読み違いを前提に、確信度を色で示して確認・編集できる",
         "要確認だけを表示、元画像の該当箇所を拡大、クリックで対応する項目へ移動"),
        ("JSON と CSV で保存する",
         "西暦に直した日付など、機械学習で使いやすい形も別に出力する"),
        ("研究用の匿名化に対応する",
         "氏名が白抜きなら「匿名化済み」、指定すれば住所・連絡先も「マスク済み」にする"),
    ])

    # 3. 画面の流れ
    s = blank(prs)
    heading(s, "画面の流れ")
    steps = [("1. 読み取り", "ファイルを入れる／カメラで撮る\n様式を自動判別して位置合わせ"),
             ("2. 確認・編集", "左に元画像、右に項目\n確信度で色分け、確定・削除・音声入力"),
             ("3. 保存・出力", "JSON / CSV\n読み取り時刻・確信度・訂正の理由も残す")]
    for i, (title, body) in enumerate(steps):
        x = 0.75 + i * 4.1
        card = s.shapes.add_shape(1, Inches(x), Inches(2.2), Inches(3.7), Inches(2.6))
        card.fill.solid()
        card.fill.fore_color.rgb = BAND
        card.line.color.rgb = LINE
        card.shadow.inherit = False
        tf = card.text_frame
        tf.word_wrap = True
        tf.margin_left = Pt(14)
        tf.margin_top = Pt(12)
        put(tf, title, size=20, bold=True, color=ACCENT, first=True, space_before=0)
        for line in body.split("\n"):
            put(tf, line, size=14, color=INK, space_before=6)
    note(s, "確認・編集は左右が別々にスクロールし、元画像をクリックすると"
            "対応する項目へ移動します。", y=5.2)

    # 4. 読み取りの仕組み
    s = blank(prs)
    heading(s, "読み取りの仕組み", "LLM に頼らず、画像処理と辞書で決められるところは決める")
    bullets(s, [
        ("① 位置合わせ", "ORB 特徴点 + RANSAC で様式を判別し、写真の歪みも補正する"),
        ("② チェック欄", "白紙様式との差分で「書き込みだけ」を残し、枠内の埋まり具合と"
                      "はみ出したレ点・丸印を合わせて判定する"),
        ("③ 数字だけの欄", "元号は様式で決まっているので数字だけを読み、"
                      "印刷された「年・月・日」で区切る"),
        ("④ テキスト欄", "OCR → 記号の除去 → 字体の正規化 → 誤字訂正 → 医療辞書との照合"),
        ("⑤ 検算", "白紙様式との差分から「およそ何文字書かれているか」を出し、"
                "読めた文字数と食い違えば確信度を下げて理由を出す"),
    ])

    # 5. ベンチマーク①
    s = blank(prs)
    heading(s, "ベンチマーク① チェック欄の判定（正解データ100通・18,600枠）",
            "頂いた正解データで測定。印の種類13通り＋二重線で訂正47件を含む")
    table(s, [
        ["", "正解率", "見落とし", "誤検出", "二重線を消せた"],
        ["作り直す前", "95.47 %", "11", "785", "0 / 47"],
        ["いま", "99.08 %", "46", "117", "39 / 47"],
    ], y=2.05, w=10.6, size=16, widths=[2.6, 2, 2, 2, 2],
        highlight=lambda r, c, v: r == 2 and c > 0)
    bullets(s, [
        ("誤検出785件は、すべて枠の中にインクが無かった",
         "差分を「枠＋周囲45%」の1つの窓で測っていたため、隣の欄の手書きを拾っていた"),
        ("書き方ごとに見る場所を分けた",
         "枠の内側 / 枠の外周（丸囲み）/ 枠の右下（はみ出し）。外周は左右の偏りで隣の字と見分ける"),
        ("二重線で消した印は、元画像から長い横線を取り出して見つける",
         "差分では線が途切れる。白紙にもある罫線を引き、枠を左右に突き抜ける線だけを数える"),
        ("ブラウザ版と558枠を突き合わせ、判定のずれ0を確認", ""),
    ], y=4.0, size=15)

    # 6. ベンチマーク②
    s = blank(prs)
    heading(s, "ベンチマーク② 文字を読むモデルの比較",
            "正解データ（72項目）と突き合わせた実測。位置合わせと欄の切り出しは共通")
    rows = ocr_bench() or [["エンジン", "文字正解率", "完全一致", "空欄の判定",
                            "拾い読み", "所要"]]
    table(s, rows, y=1.95, size=13, widths=[3.4, 2, 2, 2, 1.6, 1.6],
          highlight=lambda r, c, v: r == 1 and c > 0)
    bullets(s, [
        ("日本語専用の認識モデルに替えた（PP-OCRv4）",
         "既定のRapidOCRは中国語向け。tesseractは日本語のかな・医療用語に弱い"),
        ("罫線・カッコ・単位を切り落としてから読む",
         "白紙様式との差分で印刷と書き込みを見分ける。生読みで 78.0% → 84.6%"),
        ("書き込みが無い欄は読まない", "罫線から文字を作る「拾い読み」を防ぐ"),
        ("ブラウザ版も同じモデルを動かす（onnxruntime-web）",
         "実測 92.1%。Python版 93.0% とほぼ揃った"),
    ], y=4.0, size=15)
    note(s, "この表は2検体72項目での比較。正解データ100通での実測は次ページ。", y=6.35)

    # 6.5 正解データで文字欄を測る
    s = blank(prs)
    heading(s, "ベンチマーク②b 正解データ100通で文字欄を測る",
            "まとめた正解率では見えない外し方を、欄ごと・部分ごとに切り分けた")
    table(s, [
        ["欄", "作業前", "いま", "何が起きていたか"],
        ["ふりがな", "0.00 %", "78.1 %", "文字種の指定がカタカナだけで、ひらがなを全部捨てていた"],
        ["留意事項（その他）", "46.4 %", "88.7 %", "欄の文字の位置検出が落ちると何も読めていなかった"],
        ["体重", "70.8 %", "83.3 %", "手書きの小さな小数点を読み落とす（430→43.0 と範囲で判断）"],
        ["連絡先", "80.1 %", "86.5 %", "同上（位置検出の取りこぼし）"],
        ["文字全体", "84.3 %", "88.4 %", ""],
    ], y=1.95, size=13, widths=[2.4, 1.5, 1.5, 6.4],
       highlight=lambda r, c, v: c == 2 and r > 0)
    bullets(s, [
        ("「ふりがな」は0.00%だった。読めていたのに、後処理が全部捨てていた",
         "様式の欄名どおり、書かれるのはひらがな。カタカナだけを許していた"),
        ("日付は年・月・日を別々に測る",
         "実測は 年78.1% / 月92.4% / 日94.1%。いちばん悪いのは年（日ではない）"),
    ], y=4.9, size=15)

    # 7. ベンチマーク③（LLM）
    s = blank(prs)
    heading(s, "ベンチマーク③ LLMモデルの比較",
            "16問（うち4問は「候補を出してはいけない」問題）／ CPU のみ")
    rows = models or [["モデル", "サイズ", "正答", "安全", "1件あたり"]]
    table(s, rows, y=1.95, size=13.5, widths=[4.6, 1.6, 1.6, 2.4, 2])
    bullets(s, [
        ("辞書だけでも 12問中9問は正しく直る。LLM は「辞書に無い表記ゆれ」への保険",
         ""),
        ("短い欄（傷病名など）は候補を出すだけで、値は自動確定しない",
         "小型LLMは読み取り不能な文字列からも、もっともらしい病名を作り出すため"),
        ("記述欄（経過及び治療内容・特記すべき事項）だけは校正結果を自動反映",
         "反映前の読みは「OCR生読み」として候補に残るので、1押しで戻せる"),
    ], y=4.15, size=15)

    # 8. ベンチマーク④
    s = blank(prs)
    heading(s, "ベンチマーク④ 数字の欄と、記述欄の検算")
    table(s, [
        ["対象", "やり方", "結果"],
        ["記入日・生年月日・最終診察日・発症年月日", "元号は読まず数字だけを読み、"
         "印刷された年／月／日で区切る", "10 / 10 正解"],
        ["電話番号・郵便番号", "文字種を限定し、書式を整える", "029-873-3111 の形に統一"],
        ["記述欄の左端", "白紙様式を見て、印刷にぶつからない範囲で読み取り枠を広げる",
         "症状名は9件中9件で先頭が切れていた → 解消"],
        ["記入が無い欄の拾い読み", "書き込みが1文字ぶんも無いのに文字が読めた場合を検出",
         "449欄中28欄を検出（確信度0.8以上の誤りは0件）"],
    ], y=1.95, size=12.5, widths=[3.4, 5.2, 3.4])
    note(s, "値は書き換えず、確信度を下げて理由を出す。"
            "「読めた文字が少ないから補う」ことはしない（無い記載を作らないため）。",
         y=5.5)

    # 9. 辞書と医療機関一覧
    s = blank(prs)
    heading(s, "医療辞書と医療機関一覧")
    bullets(s, [
        ("傷病名は ICD-10 コードと介護保険の特定疾病フラグを持つ",
         "編集距離ベースの照合で1文字違いも拾う（骨粗葵症→骨粗鬆症、慢性裳臓病→慢性腎臓病）"),
        ("診療科しか入らない欄には診療科の辞書を当てる", ""),
        (f"医療機関は厚生労働省の一覧と突き合わせる"
         f"（{n_pref} 都道府県 / {n_hosp:,} 件"
         + (f" / {hosp_updated} 現在" if hosp_updated else "") + "）",
         "確認画面では都道府県を選んで検索でき、選ぶと所在地と電話も自動で入る"),
        ("辞書で「短くしてしまう」置き換えはしない",
         "『筑波記念病院』が『病院』に、『右大腿骨骨折』が『骨折』に潰れていたのを修正"),
    ])

    # 10. 確認・編集画面
    s = blank(prs)
    heading(s, "確認・編集画面の工夫", "読み違いを見つけやすく、直しやすくする")
    bullets(s, [
        ("確信度を色で示す（高・中・要確認・修正済み・確定・匿名化）",
         "タグだけでなく背景色にも反映し、元画像の該当箇所にも同じ色を重ねる"),
        ("様式と同じ並びで表示する", "選択肢の行・列、関連項目のまとまり（褥瘡＝有無＋部位＋程度）"),
        ("「確定」（黄緑）と「削除して確定」", "記入が無い欄に文字が入った場合を1操作で片付ける"),
        ("候補ボタン（辞書・LLM・OCR生読み）と、辞書からの検索", ""),
        ("記述欄は音声入力もできる", "ブラウザの音声認識を使うため、初回に確認を出す"),
        ("拡大表示は掴んで動かせる／集計は上部に固定", ""),
    ], size=16)

    # 11. 匿名化と記録
    s = blank(prs)
    heading(s, "匿名化・操作ログ・利用者の区別")
    bullets(s, [
        ("匿名化加工済みデータ（研究用）",
         "氏名欄が白抜きなら「匿名化済み」。指定すると住所・連絡先も「マスク済み」にし、"
         "元の読み取り値ごと捨てる"),
        ("操作ログ",
         "読み取り・修正（直す前→直した後）・確定・候補採用・音声入力を記録し、"
         "JSON / CSV で保存できる。個人情報の項目は値を残さず文字数だけ"),
        ("利用者トークン",
         "同じ端末を複数人が使っても履歴が混ざらないよう、ブラウザごとに発行した"
         "トークンで保存先を分ける。共用端末では作業後に消せる"),
        ("サイト全体は Basic 認証で保護", "トークンは認証ではない、と画面にも明記している"),
    ], size=16)

    # 12. 品質チェック
    s = blank(prs)
    heading(s, "品質チェックで見つけた重大な不具合",
            "「見た目は正しく確信度も高いのに中身が違う」型を、実測で洗い出した")
    table(s, [
        ["見つかった不具合", "起きていたこと"],
        ["定型文フィルタが臨床情報を消す", "『認知症』『骨折』『がん』が空になる"],
        ["病名が別の病名に化ける", "『糖尿病』→『糖尿病性腎症』を確信度100%で採用"],
        ["数字の切り詰め", "『2024年』→『20年』→ 西暦2038年"],
        ["記入が無い欄の拾い読みが素通り", "『摂食の留意事項＝い』が確信度0.816（緑）"],
        ["操作ログに個人情報", "ファイル名（氏名を含む）と医療機関名が生で残る"],
        ["編集ログが別の意見書と混ざる", "存在しない訂正が記録される"],
        ["欄が画像の端に掛かると落ちる", "1件まるごと失われる"],
        ["ふりがな欄が必ず空になる", "読めていたのに、文字種の指定で全部捨てていた（0.00%）"],
        ["診断名が粗い分類に化ける", "『右大腿骨頸部骨折術後』→『大腿骨頸部骨折』（右・術後が消える）"],
        ["同時に2件来るとサーバごと落ちる", "処理中の全部が巻き添え。小型LLMを共有していた"],
    ], y=1.95, size=13, widths=[5, 7])
    note(s, "同じ判定を Python とブラウザの両方に持つため、"
            "同じ入力で値が一致するかを必ず突き合わせる。", y=6.25)

    # 12.2 見つけ方
    s = blank(prs)
    heading(s, "不具合の見つけ方", "見る人を変えると、出てくるものが変わる")
    table(s, [
        ["やり方", "見つかったもの", "重なり"],
        ["コードを読むレビュー", "8件（無効になっていた分岐、両版のずれ、境界の1文字違い）",
         "—"],
        ["説明書だけを頼りに触る確認", "9件（同時実行で落ちる、仕様との食い違い、"
         "エラーが利用者に届かない、説明書が無い）", "0件"],
    ], y=2.0, size=13, widths=[3.2, 6.6, 2.0])
    bullets(s, [
        ("9件中1件も重ならなかった", "性質がまったく違う。両方やる必要がある"),
        ("利用者目線でいちばん重かった指摘は「説明書が1文字も無い」",
         "--help だけが手がかりで、何から始めればよいか分からない状態だった"),
        ("測って自分の判断が4回覆った",
         "輪郭立て＝害 / 切り抜き側の低解像度対応＝効果0 / Lanczosの境目＝変化なし / Lanczos自体＝差なし"),
    ], y=4.3, size=15)

    # 12.5 解像度の低い入力
    s = blank(prs)
    heading(s, "解像度の低い入力への対応",
            "人が読める程度に写っていても、機械が読めないことがある")
    table(s, [
        ["入力", "引き伸ばし", "対応後", "対応前"],
        ["200dpi（想定）", "1.0 倍", "255", "255（同じ）"],
        ["150dpi", "1.33 倍", "260", "256"],
        ["100dpi", "2.0 倍", "244", "249"],
        ["75dpi（A4が横600画素）", "2.66 倍", "241", "225"],
    ], y=1.95, w=9.6, size=14, widths=[3.6, 2, 2, 2],
       highlight=lambda r, c, v: r == 4 and c == 2)
    bullets(s, [
        ("要は「位置合わせの1行」だった",
         "テンプレートの大きさに合わせる所で線形補間を使っていた。にじんで細い線が消え、"
         "あとでいくら拡大しても戻らない"),
        ("切り抜き側をいじっても効果は0だった",
         "位置合わせで既に引き伸ばされているため、分岐に一度も入っていなかった。"
         "測って初めて分かった"),
        ("輪郭を立てる処理は悪化したので入れていない", "100dpi で 年74.0% → 70.2%"),
    ], y=4.4, size=15)
    note(s, "表の数字は20通・日付284件の正解数。低い解像度ほど効きが大きい。", y=6.5)

    # 12.6 源内
    s = blank(prs)
    heading(s, "デジタル庁「源内」への接続（受け口だけ用意・既定は閉）",
            "組み込みの可否を検討した結果")
    table(s, [
        ["検討したこと", "結論"],
        ["genai-web / genai-ai-api のコードを取り込む", "しない。前者はAWS CDKの基盤本体、"
         "後者はクラウド別のRAG/LLMテンプレート。帳票の読み取りは含まれない"],
        ["源内のAIアプリとして登録できるようにする", "受け口を用意した。"
         "取り決めは薄いREST（ファイルをbase64で受け、Markdownを返す）"],
        ["ライセンス", "両方とも MIT。障害にならない"],
    ], y=1.95, size=13, widths=[4.4, 7.4])
    bullets(s, [
        ("既定では閉じている（404）。ikensho serve --gennai と明示したときだけ開く", ""),
        ("開くと「患者情報は端末から出ない」という前提が変わる",
         "読み取り結果（氏名・生年月日・住所を含む）が源内側に渡り、履歴に残る。"
         "運用の取り決めを作ってから開くこと"),
        ("登録するかどうかは利用側の判断。技術的な準備だけ済ませてある", ""),
    ], y=4.5, size=15)

    # 13. 配布
    s = blank(prs)
    heading(s, "配布のしかた")
    table(s, [
        ["方法", "対象", "特徴"],
        ["Web版（サーバに設置）", "組織で使う", "全機能。Basic認証で保護"],
        ["Python版（pip）", "Rocky / Ubuntu / macOS", "大量処理・自動化に向く"],
        ["Docker", "Windows など", "OS を問わず同じ環境で動く"],
        ["単一HTMLファイル", "持ち運び", "チェック欄のみ（ブラウザの制約でOCRは動かない）"],
    ], y=2.0, size=14, widths=[3.2, 3.4, 5.4])
    bullets(s, [
        ("辞書・テンプレート・様式定義はデータとして分離", "新しい様式は管理画面から追加できる"),
    ], y=5.0, size=15)

    # 14. 開発の記録
    s = blank(prs)
    heading(s, "開発の記録")
    items = [
        (f"GitHub の Issue に問題を残している"
         + (f"（全 {n_issue} 件 / 未対応 {n_open} 件）" if n_issue else ""),
         "症状・原因・直し方・確認方法をそれぞれに書いている"),
        ("WORKLOG.md（作業ログ）",
         "どのコミットでどのファイルを何行いじったか、指示への対応状況の対照表"),
        ("DEVNOTES.md（開発メモ）",
         "設計の経緯、試して駄目だった方法、既知の限界"),
        ("docs/DEVELOPER.md（技術者向け）", "構成、全コマンド、新しい様式の追加手順"),
    ]
    bullets(s, items, size=16)

    # 15. これから
    s = blank(prs)
    heading(s, "懸念事項（今わかっている弱点）",
            "使う前に知っておいてほしいこと")
    table(s, [
        ["懸念", "中身", "いま言えること"],
        ["読み取りは完全ではない", "チェック 99.08%（18,600枠中171件の誤り）、"
         "文字 88.4%", "必ず原本と照らして確認する運用が前提"],
        ["枠外にはみ出した印", "正解率45.6%。隣の手書きと見分けが付かない",
         "確認画面で人が直す"],
        ["汚れの多いスキャン", "誤検出117件のうち79件が3通に集中",
         "1通単位で見分ける仕組みが要る（未着手）"],
        ["解像度の低い入力", "75dpi 相当でも読めるが、年の精度は落ちる",
         "200dpi以上での取り込みを勧める"],
        ["正解データが1種類", "100通すべて同じ生成条件。実際の紙とは傾向が違う可能性",
         "実データでの検証が要る"],
        ["源内につなぐと前提が変わる", "患者情報が端末の外に出る",
         "既定は閉。運用の取り決めが先"],
    ], y=1.9, size=12, widths=[2.8, 4.8, 4.2])
    note(s, COPYRIGHT, y=6.55, size=12)

    # 16. これから
    s = blank(prs)
    heading(s, "これから")
    bullets(s, [
        ("汚れの多い紙を1通単位で見分けて、しきい値を上げる", "誤検出の3分の2がここに集中している"),
        ("枠外にはみ出した印を拾う", "いまは45.6%"),
        ("実データでの検証", "正解データは生成物なので、実際の紙で確かめる必要がある"),
        ("単一HTMLファイル版でのテキストOCR", "ブラウザの制約があり、方法を検討中"),
        ("様式が変わったときの追従", "テンプレートも、チェック欄の言葉も管理画面から直せる"),
    ], size=16)
    note(s, COPYRIGHT, y=6.3, size=12)

    footer(prs)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    prs.save(out_path)
    return out_path, len(prs.slides._sldIdLst)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args()
    path, n = build(args.out)
    size = os.path.getsize(path) / 1024
    print(f"{n} 枚のスライドを書き出しました: {path}（{size:.0f} KB）")


if __name__ == "__main__":
    main()
