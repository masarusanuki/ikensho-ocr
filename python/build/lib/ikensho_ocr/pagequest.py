# -*- coding: utf-8 -*-
"""ページ全体を文章として読み、質問と選択肢がテンプレート通りかを確かめる。

**なぜ要るか。** 様式を Word で作り直すと、質問文はそのままでも
回答項目（選択肢）が増えたり減ったり言い回しが変わったりする。
テンプレートの座標だけを見ていると、変わったことに気づけないまま
「定義上の選択肢」の言葉で出力してしまう。

**やり方。** NDLOCR-Lite でページを1回だけ読むと、印刷された質問文・選択肢・
手書きが行ごとに並んで出てくる。例えばこう読める:

    [麻痺 □右上肢 (程度:□軽 □重) 左上肢(程度:□軽□中 Z重)

この行を□で区切れば、その質問の**実物の選択肢の言葉**が並ぶ。
テンプレートの選択肢と突き合わせて、足りない・増えているものを報告する。

**測った限界（seigo2 の3通・選択肢 489 個）。**

  - 行から拾えた選択肢の言葉 69%
  - 拾えないのは、ローマ数字（Ⅱa/Ⅲb）が崩れる欄、
    数字だけの行、行そのものが検出されない欄
  - 様式を変えていない3通での誤報は 0.7 件/ページ

したがってこれは**テンプレートの置き換えではない**。
座標での読み取りはそのまま正とし、ここは「様式が変わっていないか」の
見張りとして使う。見つからない＝様式が変わった、ではないので、
報告は「確かめてください」の重みにとどめる。
"""
import difflib
import re
from typing import Dict, List

# □らしき文字。印が付くと別の字に化けるので、化けやすい字も入れておく
MARK = re.compile(r"[□☐▢口ロ■☑▣✓✔☒×✗○●区図回]")
# 比べる前に落とす飾り
NOISE = re.compile(r"[\s　()（）「」\[\]【】:：;；,，、。\.]")
# 同じ言葉とみなす近さ
SAME = 0.72
# 行が質問の行かどうかを、枠の中心がこの範囲に入るかで決める（画素）
ROW_PAD = 6
# 選択肢の言葉として扱う長さ
WORD_MIN, WORD_MAX = 2, 14
# 崩れた読みを捨てる。日本語の字がこの割合より少ない語は読めていないとみなす
JA = re.compile(r"[ぁ-んァ-ヶ一-龥ーＡ-Ｚａ-ｚ０-９]")
JA_MIN = 0.7
# 半角の英字・記号が混じった語は読み崩れ。「量左下肢程度M+」のような語を弾く
BROKEN = re.compile(r"[A-Za-z+*/=<>~^|#$%&@\\]")


def _norm(s: str) -> str:
    return NOISE.sub("", str(s or ""))


def _close(a: str, b: str) -> bool:
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= SAME


def row_text(reader, rects: List[List[float]]) -> str:
    """その質問の枠が載っている行を、上から左から順につないだ文字列。

    選択肢が2段3段に折り返す欄があるので、**枠ひとつずつ**について
    その枠に重なる行を集める。まとめて中心を取ると、
    段と段のあいだに落ちて1行も拾えない。
    """
    if not rects:
        return ""
    W, H = reader.width, reader.height
    picked = {}
    for rx, ry, rw, rh in rects:
        y0, y1 = ry * H, (ry + rh) * H
        x0, x1 = rx * W, (rx + rw) * W
        cy = (y0 + y1) / 2
        for l in reader.lines:
            if l.y0 - ROW_PAD <= cy <= l.y1 + ROW_PAD and l.x1 >= x0 - 10 and l.x0 <= x1 + 10:
                picked[(l.y0, l.x0)] = l
    return " ".join(l.text for _, l in sorted(picked.items()))


def _readable(w: str) -> bool:
    """読めている言葉か。崩れた読みを「増えた選択肢」と言わないための関門。"""
    if not (WORD_MIN <= len(w) <= WORD_MAX):
        return False
    if BROKEN.search(w):
        return False
    return len(JA.findall(w)) >= len(w) * JA_MIN


def words_in(text: str) -> List[str]:
    """行を□で区切り、選択肢になりそうな言葉を取り出す。"""
    return [w for w in (_norm(p) for p in MARK.split(text)) if _readable(w)]


def _row_fields(by_field: Dict[str, List[List[float]]], reader) -> Dict[str, List[str]]:
    """同じ行に並ぶ欄どうしをまとめる。

    1行に複数の質問が並ぶ様式なので、**隣の質問の選択肢を
    「増えた言葉」と誤認しない**ために要る。
    """
    H = reader.height
    center = {fid: (min(r[1] for r in rs) + max(r[1] + r[3] for r in rs)) / 2 * H
              for fid, rs in by_field.items()}
    out: Dict[str, List[str]] = {}
    for fid, cy in center.items():
        out[fid] = [other for other, oy in center.items() if abs(oy - cy) <= ROW_PAD * 3]
    return out


def check(reader, boxes: List[dict], schema) -> Dict[str, dict]:
    """欄ごとに、実物の行とテンプレートの選択肢のずれを返す。

    返す辞書の値:
      行          … 実物から読めた行（人が目で確かめる用）
      見つかった  … テンプレートの選択肢のうち行にあった言葉
      見当たらない… 行に見つからなかった選択肢
      増えている  … 行にあってテンプレートにも質問文にも無い言葉
    """
    by_field: Dict[str, List[List[float]]] = {}
    for b in boxes:
        by_field.setdefault(b["field"], []).append(b["rect"])
    neighbours = _row_fields(by_field, reader)

    out: Dict[str, dict] = {}
    for fid, rects in by_field.items():
        f = schema.get(fid)
        if f is None or not f.options:
            continue
        text = row_text(reader, rects)
        if not text:
            continue
        defined = [str(o) for o in f.options]
        # 行を共有する欄の選択肢と質問文。これらは「増えた」とは言わない
        known: List[str] = []
        # 同じまとまり（BPSD の症状など）の選択肢も「増えた」とは言わない。
        # 縦に並ぶ欄は行が違っても同じ質問の続きだから
        if f.group:
            for g in schema.fields.values():
                if g.group == f.group:
                    known.extend(str(o) for o in (g.options or []))
        for other in neighbours.get(fid, [fid]):
            g = schema.get(other)
            if g is None:
                continue
            known.extend(str(o) for o in (g.options or []))
            for lab in (g.label, g.group_label):
                if lab:
                    known.append(str(lab))
        found = [o for o in defined if _norm(o) and _norm(o) in _norm(text)]
        missing = [o for o in defined if o not in found]
        extra = [w for w in words_in(text)
                 if not any(_close(w, k) for k in known)]
        out[fid] = dict(row=text, found=found, missing=missing, extra=extra)
    return out


def drift_notes(result: Dict[str, dict], schema) -> List[dict]:
    """食い違いのうち、人に見せる値打ちのあるものだけ並べる。

    **「見当たらない」はほとんどが読めなかっただけ**だった（実測）。
    印の付いた□は文字が化けるので、印の付いた選択肢ほど読めない。
    そこで「見当たらない」は、同じ行に**行き場のない言葉があるとき**
    ——つまり言い換えられた見込みがあるときだけ挙げる。

    「増えている」は、行を共有する欄の選択肢と質問文を除いたうえで、
    日本語として読めている語だけに絞ってある（`words_in`）。
    """
    notes = []
    for fid, r in sorted(result.items()):
        f = schema.get(fid)
        if f is None:
            continue
        defined = len(f.options or [])
        if not defined or not r["found"]:
            continue
        # 半分も読めていない行は、様式ではなく読みの問題とみなす
        if len(r["found"]) * 2 < defined:
            continue
        extra = list(r["extra"])
        missing = list(r["missing"]) if extra else []
        if not extra and not missing:
            continue
        notes.append(dict(field=fid, label=f.label,
                          missing=missing, extra=extra, row=r["row"]))
    return notes
