# -*- coding: utf-8 -*-
"""項目定義（スキーマ）の読み込み。"""
import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional

DEFAULT_SCHEMA = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "schema", "ikensho.schema.json")


@dataclass
class Field:
    id: str
    label: str
    type: str
    page: int
    options: Optional[List[str]] = None
    hint: str = ""
    dictionary: str = ""
    charset: str = ""
    pii: str = ""
    kind: str = ""
    era_field: str = ""
    default_era: str = ""
    always_pick: bool = False
    section_id: str = ""
    section_title: str = ""

    @property
    def is_choice(self) -> bool:
        return self.type in ("choice", "multi", "circle")

    @property
    def is_date(self) -> bool:
        return self.kind == "date_wareki"

    @property
    def is_text(self) -> bool:
        return self.type in ("text", "textarea")


@dataclass
class Schema:
    version: str
    form_name: str
    fields: Dict[str, Field] = field(default_factory=dict)
    order: List[str] = field(default_factory=list)
    sections: List[Dict[str, Any]] = field(default_factory=list)

    def __iter__(self) -> Iterator[Field]:
        for fid in self.order:
            yield self.fields[fid]

    def get(self, fid: str) -> Optional[Field]:
        return self.fields.get(fid)


def load_schema(path: str = DEFAULT_SCHEMA) -> Schema:
    with open(path, encoding="utf-8") as fp:
        raw = json.load(fp)
    sc = Schema(version=raw["version"], form_name=raw["form_name"], sections=raw["sections"])
    for sec in raw["sections"]:
        for f in sec["fields"]:
            fl = Field(id=f["id"], label=f["label"], type=f["type"], page=f.get("page", 1),
                       options=f.get("options"), hint=f.get("hint", ""),
                       dictionary=f.get("dictionary", ""),
                       charset=f.get("charset", ""), pii=f.get("pii", ""),
                       kind=f.get("kind", ""), era_field=f.get("era_field", ""),
                       default_era=f.get("default_era", ""),
                       always_pick=bool(f.get("always_pick")),
                       section_id=sec["id"], section_title=sec["title"])
            sc.fields[fl.id] = fl
            sc.order.append(fl.id)
    return sc
