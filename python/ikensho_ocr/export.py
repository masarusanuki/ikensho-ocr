# -*- coding: utf-8 -*-
"""読み取り結果の JSON / CSV 出力。ブラウザ版と同じ形式にそろえている。"""
import csv
import datetime
import io
import json
from typing import Any, Dict, List

from . import answers as answers_mod, derive
from .schema import Schema


def _flat(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "該当" if value else ""
    if isinstance(value, (list, tuple)):
        return "；".join(str(v) for v in value)
    return str(value)


def record_to_json(rec, schema: Schema) -> Dict[str, Any]:
    values, meta, answersplain = {}, {}, {}
    for f in schema:
        e = rec.fields.get(f.id)
        if e is None:
            continue
        values[f.id] = e.get("value")
        answersplain[f.id] = answers_mod.resolve(rec.fields, schema, f)
        meta[f.id] = dict(label=e.get("label"), type=e.get("type"),
                          section=e.get("section"), page=e.get("page"),
                          confidence=e.get("confidence"), level=e.get("level"),
                          edited=bool(e.get("edited")),
                          confirmed=bool(e.get("confirmed")), raw=e.get("raw"),
                          engine=e.get("engine"), llm_candidate=e.get("llm_candidate"),
                          anonymized=bool(e.get("anonymized")),
                          date=e.get("date"), era=e.get("era"),
                          gregorian=e.get("gregorian"),
                          # 診断名に当てた ICD（近い分類の場合もある）
                          icd10=e.get("icd10"), icd_name=e.get("icd_name"),
                          tokutei=e.get("tokutei"),
                          # なぜ確信度が低いのかが分かるよう、注記と訂正も残す
                          note=e.get("note") or "",
                          corrections=e.get("corrections") or [],
                          expected_chars=e.get("expected_chars"),
                          llm_applied=bool(e.get("llm_applied")))
    return dict(
        schema_version=schema.version,
        form_name=schema.form_name,
        template_id=rec.template_id,
        ocr_engine=rec.ocr_engine,
        anonymized=getattr(rec, "anonymized", False),
        read_at=getattr(rec, "read_at", None) or
                datetime.datetime.now().astimezone().isoformat(),
        sources=[dict(source=p.source, source_page=p.source_page,
                      page_index=p.page_index, matched=p.matched,
                      score=p.score, dewarped=p.dewarped) for p in rec.pages],
        warnings=rec.warnings,
        # 実物の様式と定義の食い違い（様式順JSONの「様式の食い違い」と同じ中身）
        form_drift=[dict(field=d.get("field"), label=d.get("label"),
                         missing=d.get("missing") or [],
                         extra=d.get("extra") or [], row=d.get("row"))
                    for d in getattr(rec, "form_drift", [])],
        values=values,
        # values は**選択肢の言葉**。answers は「その他（　）」に書かれた中身まで
        # 含めた、人が読む形（診療科の「その他」は書かれた名前そのものになる）。
        # どちらも answers.py の同じ関数で作るので、食い違うことはない
        answers=answersplain,
        # 機械学習や集計に使いやすい形（西暦に直した日付など）
        derived=derive.build(rec.fields, schema),
        meta=meta,
    )


def write_json(records: List[Any], schema: Schema, path: str) -> None:
    payload = dict(
        exported_at=datetime.datetime.now().astimezone().isoformat(),
        schema_version=schema.version,
        count=len(records),
        records=[record_to_json(r, schema) for r in records],
    )
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False, indent=2)


def csv_text(records: List[Any], schema: Schema) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    dkeys = derive.derived_keys(schema)
    dlabels = derive.derived_labels(schema)
    head = ["record_no", "template_id", "read_at", "anonymized", "sources", "warnings"]
    labels = ["#", "様式", "読取日時", "匿名化", "元ファイル", "警告"]
    for f in schema:
        head += [f.id, f"{f.id}__confidence"]
        labels += [f.label, "確信度"]
    # 西暦に直した日付などをまとめて末尾に置く（機械学習で使いやすいように）
    head += dkeys
    labels += [dlabels.get(k, k) for k in dkeys]
    w.writerow(head)
    w.writerow(labels)
    for i, rec in enumerate(records, 1):
        srcs = "；".join(dict.fromkeys(p.source for p in rec.pages))
        read_at = getattr(rec, "read_at", None) or \
            datetime.datetime.now().astimezone().isoformat()
        row = [i, rec.template_id or "", read_at,
               "はい" if getattr(rec, "anonymized", False) else "いいえ",
               srcs, "；".join(rec.warnings)]
        for f in schema:
            e = rec.fields.get(f.id) or {}
            # JSON の answers と同じ読み方にする。CSV だけ「その他」のままだと
            # 同じ読み取りが出力ごとに違って見えてしまう
            row += [_flat(answers_mod.resolve(rec.fields, schema, f)),
                    e.get("confidence", "")]
        d = derive.build(rec.fields, schema)
        for k in dkeys:
            v = d.get(k)
            row.append("" if v is None else ("1" if v is True else
                                             ("0" if v is False else v)))
        w.writerow(row)
    return buf.getvalue()


def write_csv(records: List[Any], schema: Schema, path: str) -> None:
    # Excel で開けるよう BOM 付き UTF-8 にする
    with open(path, "w", encoding="utf-8-sig", newline="") as fp:
        fp.write(csv_text(records, schema))

# ------------------------------------------------------- 様式の形そのままのJSON

# 項目の種類を、様式を見ている人に分かる言葉にする
_KIND_JA = {
    "text": "記述",
    "textarea": "記述（複数行）",
    "choice": "択一",
    "multi": "複数選択",
    "circle": "丸囲み",
    "flag": "有無",
}


def _option_words(entry: Dict[str, Any], f) -> List[str]:
    """選択肢の言葉。実物を OCR で読んだ／管理画面で直したものを優先する。"""
    words = entry.get("option_words")
    if isinstance(words, list) and len(words) == len(f.options or []):
        return [str(w) for w in words]
    return [str(o) for o in (f.options or [])]


def _form_item(entry: Dict[str, Any], f, fields: Dict[str, Any],
               schema: Schema) -> Dict[str, Any]:
    """様式の1項目を、そのまま読める形にする。

    チェック欄は**言葉**が要なので、選択肢の言葉と、どれに印が付いたかを返す。

    「答え」は、選択肢に付いている記入欄まで含めた読み方（`answers.py`）。
    診療科の「その他」は、そこに書かれた名前そのものになる。
    「値」は印の付いた選択肢の言葉のままなので、両方を見比べられる。
    """
    item: Dict[str, Any] = {
        "項目": f.label,
        "種類": _KIND_JA.get(f.type, f.type),
        "答え": answers_mod.resolve(fields, schema, f),
        "値": entry.get("value"),
    }
    links = f.option_texts or {}
    if f.type == "flag" and links.get(answers_mod.FLAG_KEY):
        note = (fields.get(links[answers_mod.FLAG_KEY]) or {}).get("value")
        if note:
            item["内容"] = note
    if f.options:
        words = _option_words(entry, f)
        item["選択肢"] = words
        detail = entry.get("detail") or []
        picked = entry.get("value")
        if isinstance(picked, list):
            chosen = set(picked)
        elif isinstance(picked, str):
            chosen = {picked}
        else:
            chosen = set()
        marks = []
        for i, word in enumerate(words):
            d = next((x for x in detail if x.get("opt") == i), {})
            m = {"言葉": word, "印": bool(d.get("checked")) or word in chosen}
            # 「その他（　　）」のように、選択肢に記入欄が付いていることがある
            note = (fields.get(links.get(str(f.options[i]), "")) or {}).get("value")
            if note:
                m["内容"] = note
            if d.get("struck"):
                m["二重線で訂正"] = True
            if d.get("circled"):
                m["丸囲み"] = True
            marks.append(m)
        if marks:
            item["チェック"] = marks
        if entry.get("option_words"):
            item["定義の選択肢"] = [str(o) for o in f.options]
    if f.is_date:
        item["西暦"] = entry.get("gregorian")
        if entry.get("era"):
            item["元号"] = entry.get("era")
    if entry.get("icd10"):
        item["ICD10"] = entry["icd10"]
        if entry.get("icd_name") and entry["icd_name"] != entry.get("value"):
            item["ICDの分類名"] = entry["icd_name"]
        if entry.get("tokutei"):
            item["特定疾病"] = True
    item["確信度"] = entry.get("confidence")
    item["確信度の段階"] = {"high": "高", "medium": "中", "low": "低",
                            "edited": "修正", "done": "確定"}.get(
        entry.get("level"), entry.get("level"))
    if entry.get("confirmed"):
        item["確認済み"] = True
    if entry.get("edited"):
        item["人が直した"] = True
    if entry.get("note"):
        item["注記"] = entry["note"]
    for note in (entry.get("label_notes") or []):
        if note.get("changed"):
            item.setdefault("言葉の食い違い", []).append(
                {"定義": note.get("expected"), "読めた言葉": note.get("read")})
    item["項目ID"] = f.id
    return item


def record_to_form_json(rec, schema: Schema) -> Dict[str, Any]:
    """様式（PDF）の並びそのままの JSON。

    節 → まとまり → 項目 の順に入れ子にしてあり、上から読めば様式と同じ順になる。
    チェック欄は**言葉**で返す（どの選択肢に印が付いたかが要なので）。
    """
    sections: List[Dict[str, Any]] = []
    for sec in schema.sections:
        items: List[Dict[str, Any]] = []
        groups: Dict[str, Dict[str, Any]] = {}
        pages = set()
        for sf in sec.get("fields", []):
            f = schema.get(sf.get("id"))
            entry = rec.fields.get(sf.get("id"))
            if f is None or entry is None:
                continue
            pages.add(f.page)
            item = _form_item(entry, f, rec.fields, schema)
            if f.group:
                g = groups.get(f.group)
                if g is None:
                    g = {"まとまり": f.group_label or f.group, "項目": []}
                    groups[f.group] = g
                    items.append(g)
                g["項目"].append(item)
            else:
                items.append(item)
        if not items:
            continue
        sections.append({
            "表題": sec.get("title") or sec.get("id"),
            "ページ": sorted(pages)[0] if pages else None,
            "項目": items,
        })
    return {
        "様式": schema.form_name,
        "様式ID": rec.template_id,
        "定義の版": schema.version,
        "読取日時": getattr(rec, "read_at", None) or
                    datetime.datetime.now().astimezone().isoformat(),
        "読み取りに使ったOCR": rec.ocr_engine,
        "匿名化済み": getattr(rec, "anonymized", False),
        "元ファイル": [dict(ファイル=p.source, ページ=p.source_page,
                            様式のページ=p.page_index, 判別できた=p.matched)
                       for p in rec.pages],
        "注意": list(rec.warnings),
        # 実物の様式と定義の食い違い。質問はそのままでも選択肢が変わることがあるので、
        # 読み取った値とは別に、様式そのものの変化をここに出す
        "様式の食い違い": [
            {"項目": d.get("label"), "項目ID": d.get("field"),
             "定義にあって読めなかった言葉": d.get("missing") or [],
             "実物にあって定義に無い言葉": d.get("extra") or [],
             "読めた行": d.get("row")}
            for d in getattr(rec, "form_drift", [])
        ],
        "節": sections,
    }


def write_form_json(records: List[Any], schema: Schema, path: str) -> None:
    payload = dict(
        書き出し日時=datetime.datetime.now().astimezone().isoformat(),
        件数=len(records),
        意見書=[record_to_form_json(r, schema) for r in records],
    )
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------
# **そのまま LLM への指示文（プロンプト）として読める形**にする。
# 表は Markdown の表にし、確信度の低いところに印を付ける。
# 読み取りの誤りが混じることを、文書の先頭で必ず断る。

_LEVEL_JA = {"high": "高", "medium": "中", "low": "低",
             "edited": "修正", "done": "確定"}
# この確信度より下は「要確認」として印を付ける
MD_LOW = 0.80
MD_MARK = "⚠"
# 空欄であることを、行の抜けと取り違えられないようにする
MD_EMPTY = "（空欄）"
# LLM が読み崩れを直した欄。**直したことを隠さない**
MD_LLM = "✎"


def _md_cell(value: Any) -> str:
    """表のマスに入れる文字。改行と縦棒は表を壊すので置き換える。"""
    if value is None or value is False:
        return ""
    if value is True:
        return "該当"
    if isinstance(value, (list, tuple)):
        value = "、".join(str(v) for v in value if str(v) != "")
    return str(value).replace("|", "｜").replace("\n", " ").strip()


def _md_level(entry: Dict[str, Any]) -> str:
    lv = _LEVEL_JA.get(entry.get("level"), entry.get("level") or "")
    conf = entry.get("confidence")
    mark = MD_LLM if entry.get("llm_applied") else ""
    if conf is None:
        return f"{lv}{mark}".strip()
    if conf < MD_LOW and entry.get("level") not in ("edited", "done"):
        mark = MD_MARK + mark
    return f"{lv} {conf:.2f}{mark}".strip()


def _md_answer(rec, schema: Schema, f, entry: Dict[str, Any]) -> str:
    """表に入れる答え。日付は西暦も添える（和暦だけでは比べられないため）。"""
    ans = _md_cell(answers_mod.resolve(rec.fields, schema, f))
    if not ans:
        return MD_EMPTY
    if f.is_date:
        era = entry.get("era") or ""
        greg = entry.get("gregorian") or ""
        if era and not ans.startswith(era):
            ans = f"{era}{ans}"
        if greg:
            ans = f"{ans}（{greg}）"
    return ans


def markdown_text(rec, schema: Schema) -> str:
    """読み取り結果を Markdown にする。そのまま読ませられる文書にする。"""
    out: List[str] = []
    add = out.append
    # 選択肢の答えに取り込んだ記入欄。答えの中に出ているので表では繰り返さない
    absorbed = answers_mod.used_text_fields(schema)
    read_at = getattr(rec, "read_at", None) or \
        datetime.datetime.now().astimezone().isoformat()

    add(f"# {schema.form_name} 読み取り結果")
    add("")
    add("これは紙の主治医意見書を OCR で読み取った結果です。"
        "**読み取りには誤りが含まれます。**")
    add(f"確信度が {MD_LOW:.2f} 未満の欄には {MD_MARK} を、"
        f"読み崩れをLLMが直した欄には {MD_LLM} を付けてあります。"
        "原本と照らして確かめてください。")
    add("")
    add(f"- 様式: {rec.template_id or '不明'}")
    add(f"- 読み取り日時: {read_at}")
    add(f"- 読み取りに使った OCR: {rec.ocr_engine}")
    if getattr(rec, "anonymized", False):
        add("- **匿名化加工済み**（氏名・住所・連絡先はマスクしてあります）")
    add("")

    for sec in schema.sections:
        rows: List[str] = []
        for sf in sec.get("fields", []):
            f = schema.get(sf.get("id"))
            entry = rec.fields.get(sf.get("id")) if f else None
            if f is None or entry is None:
                continue
            # 選択肢に取り込んだ記入欄は、答えの中に出ているので繰り返さない
            if sf.get("id") in absorbed:
                continue
            ans = _md_answer(rec, schema, f, entry)
            rows.append(f"| {_md_cell(f.label)} | {ans} | {_md_level(entry)} |")
        if not rows:
            continue
        add(f"## {sec.get('title') or sec.get('id')}")
        add("")
        add("| 項目 | 答え | 確信度 |")
        add("|---|---|---|")
        out.extend(rows)
        add("")

    # 空欄で確信度が低いものまで並べると、どの様式でも十数行になって埋もれる。
    # **読めた値があるのに確信が持てないもの**だけを挙げる（空欄は表に印が付く）
    check = [f for f in schema
             if (rec.fields.get(f.id) or {}).get("confidence") is not None
             and (rec.fields.get(f.id) or {}).get("confidence") < MD_LOW
             and (rec.fields.get(f.id) or {}).get("level") not in ("edited", "done")
             and _md_cell(answers_mod.resolve(rec.fields, schema, f))]
    if check:
        add("## 確かめてほしいところ")
        add("")
        for f in check:
            e = rec.fields[f.id]
            note = e.get("note") or ""
            raw = e.get("raw") or ""
            extra = []
            if raw and raw != str(e.get("value") or ""):
                extra.append(f"OCRの生読み「{_md_cell(raw)}」")
            if note:
                extra.append(_md_cell(note))
            tail = f"（{' / '.join(extra)}）" if extra else ""
            add(f"- **{f.label}**: "
                f"{_md_answer(rec, schema, f, e)}{tail}")
        add("")

    drift = getattr(rec, "form_drift", [])
    if drift:
        add("## 様式が定義と食い違って見えるところ")
        add("")
        add("**実物の様式と、こちらが持っている選択肢の定義が食い違って見えます。**")
        add("読み崩れのこともあるので、自動では直していません。")
        add("")
        for d in drift:
            add(f"- **{d.get('label')}**")
            if d.get("missing"):
                add(f"  - 定義にあって読めなかった言葉: {'、'.join(d['missing'])}")
            if d.get("extra"):
                add(f"  - 実物にあって定義に無い言葉: {'、'.join(d['extra'])}")
            if d.get("row"):
                add(f"  - 読めた行: `{_md_cell(d['row'])}`")
        add("")

    if rec.warnings:
        add("## 注意")
        add("")
        for w in rec.warnings:
            add(f"- {_md_cell(w)}")
        add("")

    add("## 元ファイル")
    add("")
    for p in rec.pages:
        ok = "判別できた" if p.matched else "**判別できなかった**"
        add(f"- {p.source} の {p.source_page} ページ目 "
            f"→ 様式の {p.page_index} ページ目（{ok}）")
    add("")
    return "\n".join(out)


def write_markdown(records: List[Any], schema: Schema, path: str) -> None:
    parts = [markdown_text(r, schema) for r in records]
    body = "\n\n---\n\n".join(parts)
    if len(records) > 1:
        body = f"# 読み取り結果 {len(records)} 件\n\n---\n\n" + body
    with open(path, "w", encoding="utf-8") as fp:
        fp.write(body)
