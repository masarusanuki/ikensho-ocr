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
                          edited=bool(e.get("edited")), raw=e.get("raw"),
                          engine=e.get("engine"), llm_candidate=e.get("llm_candidate"),
                          anonymized=bool(e.get("anonymized")),
                          date=e.get("date"), era=e.get("era"),
                          gregorian=e.get("gregorian"))
    return dict(
        schema_version=schema.version,
        form_name=schema.form_name,
        template_id=rec.template_id,
        ocr_engine=rec.ocr_engine,
        anonymized=getattr(rec, "anonymized", False),
        read_at=datetime.datetime.now().astimezone().isoformat(),
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
    now = datetime.datetime.now().astimezone().isoformat()
    for i, rec in enumerate(records, 1):
        srcs = "；".join(dict.fromkeys(p.source for p in rec.pages))
        row = [i, rec.template_id or "", now,
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
