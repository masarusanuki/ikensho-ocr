# -*- coding: utf-8 -*-
"""検証データの生成元（layout.js）から、様式テンプレートを作る。

新しい検証データ（`seigo2/`・1,000通）には**生成元のソース**が入っている。
そこには枠と記入欄の座標がそのまま書かれているので、
**推測せずに座標を確定できる**。

これまでは別様式のテキスト欄座標を推測で写していた（開発メモ 3.3）。
そのため新しい検証データで文字の正解率が45%まで落ちていた
（読み取りの問題ではなく、読む場所がずれていた）。

    node tools/dump_layout.js seigo2/src/layout.js out.json   # 座標を取り出す
    python3 tools/build_template_from_source.py --layout out.json --id seigo2_v1

生成元: seigo2/src/layout.js（150dpi A4 = 1240x1754 で描かれている）
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "python"))

from ikensho_ocr.schema import load_schema      # noqa: E402

# 生成元の記入欄ID → 我々の項目id
ANCHOR_MAP = {
    "furigana": "applicant_furigana", "name": "applicant_name",
    "zip": "postal_code", "address": "applicant_address", "age": "age",
    "tel2": "applicant_phone", "doctor": "doctor_name",
    "hospital": "clinic_name", "h_addr": "clinic_address",
    "h_tel_b": "clinic_phone", "h_fax_b": "clinic_fax",
    "dept_other_txt": "other_dept_other_text",
    "dx1": "diagnosis1_name", "dx2": "diagnosis2_name", "dx3": "diagnosis3_name",
    "stab_note": "stability_detail", "course": "treatment_course",
    "psy_name": "other_psych_symptom_name",
    "psy_spec_txt": "specialist_consult_detail",
    "height": "height_cm", "weight": "weight_kg",
    "limb_site": "limb_defect_site", "para_other_site": "paralysis_other_site",
    "site_筋力": "muscle_weakness_site", "site_拘縮": "joint_contracture_site",
    "site_痛み": "joint_pain_site", "site_褥瘡": "pressure_ulcer_site",
    "site_皮膚": "other_skin_disease_site",
    "nut_note": "nutrition_note", "risk_other_txt": "risk_other_text",
    "risk_plan": "risk_policy", "svc_other_txt": "service_other_text",
    "note_blood_txt": "caution_bp_text", "note_eat_txt": "caution_eating_text",
    "note_swal_txt": "caution_swallow_text", "note_move_txt": "caution_move_text",
    "note_exer_txt": "caution_exercise_text", "note_other_txt": "caution_other_text",
    "inf_txt": "infection_detail", "remarks": "special_notes",
    "bpsd_other_txt": "bpsd_symptom_text",
}
# 年・月・日に分かれている記入欄は、まとめて1つの日付欄にする
DATE_GROUPS = {
    "entry_date": ("fill_era_y", "fill_era_m", "fill_era_d"),
    "birth_date": ("birth_y", "birth_m", "birth_d"),
    "last_exam_date": ("visit_y", "visit_m", "visit_d"),
    "diagnosis1_date": ("dx1_y", "dx1_m", "dx1_d"),
    "diagnosis2_date": ("dx2_y", "dx2_m", "dx2_d"),
    "diagnosis3_date": ("dx3_y", "dx3_m", "dx3_d"),
}
# 丸で囲む欄
CIRCLE_MAP = {"applicant_sex": ("sex_m", "sex_f"), "birth_era": ("birth_era",)}

# 生成元は基準線（ベースライン）と幅しか持たないので、矩形の高さは字の大きさから補う。
# ink.js: size = round((19+0..3) * mul), sizeBig = round((27+0..4) * mul),
#         sizeSmall = round((18+0..2) * mul), mul = 0.95+rand*0.3（最大 1.25）
SIZE_MAX = {"normal": 28, "big": 39, "small": 25}   # それぞれの最大文字サイズ
UP_PAD = 4           # 基準線より上の余裕（手書きの縦揺れ）
DOWN_PAD = 4         # 下の余裕


def _size_kind(a):
    if a.get("multiline"):
        return "small"
    return "big" if a.get("big") else "normal"


def rect_of(a, W, H):
    """記入欄（基準線＋幅）を、正規化した矩形にする。

    基準線 a['y'] に対して字は上へ size、下へ size*0.25 ほど伸びる。
    複数行の欄は行送り（lh）ぶんだけ下に伸ばす。
    align:'center' は「a.x から幅 a.w の中で中央寄せ」なので、枠は左寄せと同じ。
    """
    size = SIZE_MAX[_size_kind(a)]
    up = size + UP_PAD
    down = round(size * 0.25) + DOWN_PAD
    lines = int(a.get("multiline") or 0)
    if lines:
        down += lines * int(a.get("lh") or 30)
    return [round(a["x"] / W, 6), round((a["y"] - up) / H, 6),
            round(a["w"] / W, 6), round((up + down) / H, 6)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--layout", required=True, help="dump_layout.js が書き出した JSON")
    ap.add_argument("--id", default="seigo2_v1")
    ap.add_argument("--name", default="主治医意見書（検証用サンプル2）")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    with open(args.layout, encoding="utf-8") as fh:
        layout = json.load(fh)
    schema = load_schema()

    pages = []
    unknown_boxes, unknown_anchors = [], []
    for pno in ("1", "2"):
        page = layout[pno]
        W, H = page["W"], page["H"]
        anchors = {a["id"]: a for a in page["anchors"]}

        texts = []
        for aid, fid in ANCHOR_MAP.items():
            a = anchors.get(aid)
            if a is None:
                continue
            f = schema.get(fid)
            if f is None:
                unknown_anchors.append(fid)
                continue
            texts.append(dict(
                field=fid, type=f.type, rect=rect_of(a, W, H),
                options=None, charset=f.charset, pii=f.pii, kind=f.kind,
                era_field=f.era_field, default_era=f.default_era,
                always_pick=False, placement="生成元から"))
        # 日付欄は年・月・日をまとめ、小枠も残す
        for fid, parts in DATE_GROUPS.items():
            got = [anchors[p] for p in parts if p in anchors]
            if len(got) != 3:
                continue
            f = schema.get(fid)
            if f is None:
                continue
            rs = [rect_of(a, W, H) for a in got]
            x0 = min(r[0] for r in rs)
            x1 = max(r[0] + r[2] for r in rs)
            y0 = min(r[1] for r in rs)
            texts.append(dict(
                field=fid, type=f.type,
                rect=[round(x0, 6), round(y0, 6), round(x1 - x0, 6),
                      round(max(r[3] for r in rs), 6)],
                options=None, charset=f.charset, pii=f.pii, kind=f.kind,
                era_field=f.era_field, default_era=f.default_era,
                always_pick=False, placement="生成元から",
                slots=dict(year=rs[0], month=rs[1], day=rs[2])))
        for fid, parts in CIRCLE_MAP.items():
            got = [anchors[p] for p in parts if p in anchors]
            if not got:
                continue
            f = schema.get(fid)
            if f is None:
                continue
            rs = [rect_of(a, W, H) for a in got]
            x0 = min(r[0] for r in rs)
            x1 = max(r[0] + r[2] for r in rs)
            texts.append(dict(
                field=fid, type=f.type,
                rect=[round(x0, 6), round(min(r[1] for r in rs), 6),
                      round(x1 - x0, 6), round(max(r[3] for r in rs), 6)],
                options=f.options, charset="", pii="", kind="",
                era_field="", default_era="", always_pick=bool(f.always_pick),
                placement="生成元から"))

        boxes = []
        for b in page["boxes"]:
            fid, opt = box_field(b["id"], schema)
            if fid is None:
                unknown_boxes.append(b["id"])
                continue
            boxes.append(dict(field=fid, opt=opt,
                              rect=[round(b["x"] / W, 6), round(b["y"] / H, 6),
                                    round(b["s"] / W, 6), round(b["s"] / H, 6)]))
        pages.append(dict(index=int(pno), width=1654, height=2339,
                          ref=f"{args.id}_p{pno}.png", blank=f"{args.id}_p{pno}.png",
                          boxes=boxes, texts=texts))

    tpl = dict(id=args.id, name=args.name, schema_version=schema.version,
               page_count=len(pages), aspect=round(1754 / 1240, 6), pages=pages)
    out = args.out or os.path.join(ROOT, "templates", f"{args.id}.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(tpl, fh, ensure_ascii=False, indent=1)
    n_b = sum(len(p["boxes"]) for p in pages)
    n_t = sum(len(p["texts"]) for p in pages)
    print(f"書き出しました: {out}")
    print(f"  チェック欄 {n_b} 個 / テキスト欄 {n_t} 個")
    if unknown_boxes:
        print(f"  対応づけできなかった枠 {len(unknown_boxes)} 個: "
              f"{', '.join(sorted(set(unknown_boxes))[:12])}")
    print("  ※参照画像（refs/blanks）は別途用意が要る")


# 生成元の枠ID の接頭辞 → 我々の項目id。
# 接尾辞は選択肢の言葉なので、項目定義の options と突き合わせる。
# **ここが様式の読み方そのもの。** 合わないものは対応づけできなかったとして出す。
PREFIX_FIELD = {
    "consent": "consent", "times": "report_count", "other": "other_dept_visit",
    "dept": "other_dept", "stab": "symptom_stability", "med": "special_med_procedure",
    "adl": "adl_disabled", "dem": "adl_dementia", "mem": "short_term_memory",
    "dec": "decision_ability", "com": "communication_ability",
    "bpsd": "bpsd_items", "psy": "other_psych_presence",
    "hand": "dominant_hand", "wchg": "weight_change",
    "walk": "outdoor_walking", "wc": "wheelchair", "aid": "walking_aid",
    "eat": "eating", "nut": "nutrition_status", "risk": "risk_conditions",
    "prog": "service_outlook", "svc": "medical_management", "inf": "infection",
    "note": "service_caution",
}
# 生成元では1つの接頭辞でも、こちらでは別項目に分かれているもの
SPLIT_FIELD = {
    "med_モニター測定": ("special_med_response", "モニター測定"),
    "med_褥瘡の処置": ("special_med_response", "褥瘡の処置"),
    "med_カテーテル": ("special_med_incontinence", "カテーテル"),
    "bpsd_無": ("bpsd_presence", "無"), "bpsd_有": ("bpsd_presence", "有"),
    "consent_yes": ("consent", "同意する"), "consent_no": ("consent", "同意しない"),
    "eat_自立": ("eating", "自立ないし何とか自分で食べられる"),
    "wc_主に自分で操作": ("wheelchair", "主に自分で操作している"),
    "wc_主に他人が操作": ("wheelchair", "主に他人が操作している"),
    "note_特記なし": ("service_caution", "特記すべき項目なし"),
    "svc_特記なし": ("medical_management", "特記すべき項目なし"),
}
# 接尾辞の言葉が項目定義と少し違うもの
ALIAS = {
    "yes": "有", "no": "無", "first": "初回", "more": "2回目以上",
    "stable": "安定", "unstable": "不安定", "unknown": "不明",
    "ok": "問題なし", "ng": "問題あり",
    "blood": "血圧", "eat": "摂食", "swal": "嚥下", "move": "移動",
    "exer": "運動", "other": "その他",
}
# 部位ごとに「軽・中・重」を持つ欄（`筋力の低下_軽` のような形）
DEGREE_FIELD = {
    "筋力の低下": "muscle_weakness", "関節の拘縮": "joint_contracture",
    "関節の痛み": "joint_pain", "褥瘡": "pressure_ulcer",
    "その他の皮膚疾患": "other_skin_disease",
}


def _match_option(field, label, schema):
    """選択肢の言葉から番号を求める。表記の揺れを少し吸収する。"""
    f = schema.get(field)
    if f is None or not f.options:
        return None
    label = ALIAS.get(label, label)
    opts = list(f.options)
    if label in opts:
        return opts.index(label)
    # 全角半角・中黒のゆれ
    import unicodedata
    norm = lambda s: unicodedata.normalize("NFKC", s).replace("・", "").replace("･", "")
    for i, o in enumerate(opts):
        if norm(o) == norm(label):
            return i
    return None


def box_field(bid, schema):
    """枠のIDから (項目id, 選択肢の番号) を求める。"""
    if bid in SPLIT_FIELD:
        fid, label = SPLIT_FIELD[bid]
        return fid, _match_option(fid, label, schema)
    if "_" in bid:
        head, tail = bid.split("_", 1)
    else:
        head, tail = bid, ""
    # 部位ごとの「有無」と「軽・中・重」
    if head in DEGREE_FIELD:
        base = DEGREE_FIELD[head]
        if tail in ("軽", "中", "重"):
            return f"{base}_degree", ["軽", "中", "重"].index(tail)
        if tail == "":
            return base, 0            # 有無は接尾辞なし（flag）
        return None, None
    # 麻痺（部位 × 程度）
    if head == "para":
        if tail == "":
            return "paralysis", 0
        parts = tail.split("_")
        site = parts[0]
        table = {"右上肢": "paralysis_right_upper", "左上肢": "paralysis_left_upper",
                 "右下肢": "paralysis_right_lower", "左下肢": "paralysis_left_lower",
                 "その他": "paralysis_other"}
        base = table.get(site)
        if base is None:
            return None, None
        if len(parts) == 1:
            return base, 0            # 有無は接尾辞なし（flag）
        if parts[1] in ("軽", "中", "重"):
            return f"{base}_degree", ["軽", "中", "重"].index(parts[1])
        return None, None
    if head == "ataxia":
        # `上肢_右` のように 部位_左右。項目は部位ごと、選択肢が左右
        site, _, side = tail.partition("_")
        table = {"上肢": "ataxia_upper", "下肢": "ataxia_lower",
                 "体幹": "ataxia_trunk"}
        fid = table.get(site)
        if fid is None:
            return None, None
        return fid, _match_option(fid, side, schema)
    if head == "limb":
        return "limb_defect", 0
    if head == "失調不随意":
        return "ataxia", 0
    fid = PREFIX_FIELD.get(head)
    if fid is None:
        return None, None
    # spec_有 / spec_無 のような入れ子
    if tail.startswith("spec_"):
        return "specialist_consult", _match_option("specialist_consult",
                                                   tail[5:], schema)
    # 有無だけの項目（flag）は選択肢を持たない
    f = schema.get(fid)
    if f is not None and f.type == "flag" and tail in ("有", "無", "yes", "no"):
        return (fid, 0) if ALIAS.get(tail, tail) == "有" else (None, None)
    opt = _match_option(fid, tail, schema)
    if opt is None:
        return None, None
    return fid, opt


if __name__ == "__main__":
    main()
