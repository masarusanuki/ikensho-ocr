# -*- coding: utf-8 -*-
"""読み取り結果の JSON / CSV 出力。ブラウザ版と同じ形式にそろえている。"""
import csv
import datetime
import io
import json
from typing import Any, Dict, List

from . import derive
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
    values, meta = {}, {}
    for f in schema:
        e = rec.fields.get(f.id)
        if e is None:
            continue
        values[f.id] = e.get("value")
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
        values=values,
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
            row += [_flat(e.get("value")), e.get("confidence", "")]
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


def _form_item(entry: Dict[str, Any], f) -> Dict[str, Any]:
    """様式の1項目を、そのまま読める形にする。

    チェック欄は**言葉**が要なので、選択肢の言葉と、どれに印が付いたかを返す。
    """
    item: Dict[str, Any] = {
        "項目": f.label,
        "種類": _KIND_JA.get(f.type, f.type),
        "値": entry.get("value"),
    }
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
            item = _form_item(entry, f)
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
