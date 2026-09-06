# -*- coding: utf-8 -*-
"""テキスト欄の位置を、チェックボックスを基準にして決める。

チェックボックス186個の座標は、どの様式でも自動生成で正確に求まる。
一方テキスト欄は様式ごとに位置が違い、座標をそのまま写しても合わない。

そこで「このチェックボックスの右」「この2つのチェックボックスの間」という
**相対的な決め方**を1度だけ定義しておき、各様式のチェックボックス座標から
実際の位置を計算する。様式が変わっても定義はそのまま使える。

  after   : 指定のチェックボックスの右側
  between : 2つのチェックボックスの間
  span    : 指定のチェックボックスの行で、横位置は割合で指定
  row     : 縦位置だけをチェックボックスの行に合わせ、横位置は割合で指定
"""

def char_width(page):
    """その様式での全角1文字ぶんの幅。チェックボックスの幅とほぼ同じ。"""
    boxes = page.get("boxes") or []
    if not boxes:
        return 0.0132
    return sum(b["rect"][2] for b in boxes) / len(boxes)


def after(field, opt, chars=0, width=0.15, pad=0.004):
    """チェックボックスの右。chars はラベルの文字数。"""
    return dict(kind="after", ref=(field, opt), chars=chars, width=width, pad=pad)


def between(a, b, chars=0, pad=0.006, right_pad=0.010):
    """2つのチェックボックスの間。a=(field,opt) の右から b=(field,opt) の左まで。"""
    return dict(kind="between", ref=a, ref2=b, chars=chars, pad=pad, right_pad=right_pad)


def span(field, opt, x0, x1):
    """縦位置はそのチェックボックスの行、横位置はページ幅に対する割合。"""
    return dict(kind="span", ref=(field, opt), x0=x0, x1=x1)


def rows(field, opt, x0, x1, dy=0.0, height=None):
    """行を基準に、上下にずらして配置する（部位欄など）。"""
    return dict(kind="span", ref=(field, opt), x0=x0, x1=x1, dy=dy, height=height)


# ---------------------------------------------------------------------------
# 項目ごとの配置定義
#   ここに無い項目は、様式ごとの実測（枠・記入位置）から決める。
# ---------------------------------------------------------------------------
PLACEMENT = {
    # --- 1ページ目 -------------------------------------------------------
    "other_dept_other_text":           after("other_dept", 12, chars=4.4, width=0.1545),
    "bpsd_other_text":                 after("bpsd_items", 11, chars=5.5, width=0.1781),
    # --- 2ページ目 -------------------------------------------------------
    "other_psych_symptom_name":        between(("other_psych_presence", 1), ("specialist_consult", 0), chars=9.6, right_pad=0.1449),
    "specialist_consult_detail":       between(("specialist_consult", 0), ("specialist_consult", 1), chars=1.3, right_pad=0.0071),
    "limb_defect_site":                after("limb_defect", 0, chars=16.3, width=0.4048),
    "paralysis_other_site":            between(("paralysis_other", 0), ("paralysis_other_degree", 0), chars=9.6, right_pad=0.0556),
    "muscle_weakness_site":            between(("muscle_weakness", 0), ("muscle_weakness_degree", 0), chars=16.2, right_pad=0.0555),
    "joint_contracture_site":          between(("joint_contracture", 0), ("joint_contracture_degree", 0), chars=16.4, right_pad=0.0573),
    "joint_pain_site":                 between(("joint_pain", 0), ("joint_pain_degree", 0), chars=16.3, right_pad=0.0555),
    "pressure_ulcer_site":             between(("pressure_ulcer", 0), ("pressure_ulcer_degree", 0), chars=16.4, right_pad=0.0573),
    "other_skin_disease_site":         between(("other_skin_disease", 0), ("other_skin_disease_degree", 0), chars=16.3, right_pad=0.0555),
    "risk_other_text":                 after("risk_conditions", 13, chars=5.5, width=0.1697),
    "medical_management_other_text":   after("medical_management", 11, chars=12.8, width=0.1361),
    "caution_bp_text":                 after("service_caution", 0, chars=3.5, width=0.2184),
    "caution_eating_text":             after("service_caution", 1, chars=3.5, width=0.2016),
    "caution_swallow_text":            after("service_caution", 2, chars=3.6, width=0.252),
    "caution_move_text":               after("service_caution", 3, chars=3.5, width=0.2184),
    "caution_exercise_text":           after("service_caution", 4, chars=3.5, width=0.2016),
    "caution_other_text":              after("service_caution", 5, chars=4.9, width=0.2352),
    "infection_detail":                between(("infection", 1), ("infection", 2), chars=4.1, right_pad=0.0124),
}


def box_map(page):
    return {(b["field"], b["opt"]): b["rect"] for b in page["boxes"]}


def resolve(field_id, page, boxes=None):
    """配置定義から、その様式での矩形（正規化座標）を計算する。

    定義が無い、または基準のチェックボックスが無い場合は None。
    """
    rule = PLACEMENT.get(field_id)
    if not rule:
        return None
    boxes = boxes if boxes is not None else box_map(page)
    ch = char_width(page)
    ref = boxes.get(tuple(rule["ref"]))
    if not ref:
        return None
    bx, by, bw, bh = ref
    # 縦位置は基準のチェックボックスの行に合わせ、少し上下に広げる
    y0 = by - bh * 0.28
    h = bh * 1.56

    if rule["kind"] == "after":
        x0 = bx + bw + rule["chars"] * ch + rule["pad"]
        x1 = x0 + rule["width"]
    elif rule["kind"] == "between":
        ref2 = boxes.get(tuple(rule["ref2"]))
        if not ref2:
            return None
        x0 = bx + bw + rule["chars"] * ch + rule["pad"]
        x1 = ref2[0] - rule["right_pad"]
    else:                                   # span
        x0, x1 = rule.get("x0"), rule.get("x1")
        if x0 is None or x1 is None:
            return None
        if rule.get("dy"):
            y0 += rule["dy"]
        if rule.get("height"):
            h = rule["height"]

    if x1 - x0 < 0.02:
        return None
    return [round(max(0.0, x0), 6), round(max(0.0, y0), 6),
            round(min(1.0, x1 - x0), 6), round(min(1.0, h), 6)]
