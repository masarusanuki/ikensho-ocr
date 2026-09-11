# -*- coding: utf-8 -*-
"""機械学習や集計に使いやすい形の値を、読み取り結果から導く。

和暦のままでは比較も差分計算もできないので、**西暦に直したものを別に持つ**。
読み取った元の値は残したまま、派生値として並べて保存する。
"""
import datetime
import re
from typing import Any, Dict, Optional

from . import dates as dates_mod


def _iso(entry: Dict) -> Optional[str]:
    return entry.get("gregorian") if entry else None


def _int(value: Any) -> Optional[int]:
    if value is None:
        return None
    m = re.search(r"\d+", str(value))
    return int(m.group(0)) if m else None


def _full_date(iso: Optional[str]) -> Optional[datetime.date]:
    """YYYY-MM-DD の形になっているものだけ日付として扱う。"""
    if not iso or len(iso) != 10:
        return None
    try:
        return datetime.date.fromisoformat(iso)
    except ValueError:
        return None


def _age(birth: Optional[str], at: Optional[str]) -> Optional[int]:
    b, a = _full_date(birth), _full_date(at)
    if not b or not a:
        return None
    years = a.year - b.year - ((a.month, a.day) < (b.month, b.day))
    return years if 0 <= years <= 130 else None


def build(fields: Dict[str, dict], schema) -> Dict[str, Any]:
    """派生値をまとめる。

    - 日付は西暦の ISO 形式（`YYYY-MM-DD`）で持つ。日が読めていなければ
      `YYYY-MM`、年だけなら `YYYY` になる
    - 生年月日と記入日がそろえば年齢を計算し、様式に書かれた年齢と突き合わせる
    """
    out: Dict[str, Any] = {}
    for f in schema:
        if f.id.startswith("diagnosis") and f.id.endswith("_name"):
            e = fields.get(f.id) or {}
            out[f"{f.id}_icd10"] = e.get("icd10")
            out[f"{f.id}_tokutei"] = e.get("tokutei")
    for f in schema:
        if getattr(f, "kind", "") != "date_wareki":
            continue
        e = fields.get(f.id) or {}
        out[f"{f.id}_iso"] = _iso(e)
        out[f"{f.id}_era"] = e.get("era") or ""
        d = e.get("date") or {}
        out[f"{f.id}_year"] = d.get("year")
        out[f"{f.id}_month"] = d.get("month")
        out[f"{f.id}_day"] = d.get("day")

    birth = out.get("birth_date_iso")
    # 年月日がそろっている方を使う（片方が欠けていても計算できるように）
    entry = next((out.get(k) for k in ("entry_date_iso", "last_exam_date_iso")
                  if _full_date(out.get(k))), None)
    computed = _age(birth, entry)
    written = _int((fields.get("age") or {}).get("value"))
    out["age_computed"] = computed
    out["age_written"] = written
    # 記載の年齢と計算した年齢が食い違えば、どちらかの読み取りが誤っている
    out["age_matches"] = (None if computed is None or written is None
                          else abs(computed - written) <= 1)
    return out


def derived_keys(schema) -> list:
    """CSV の列順を決めるためのキー一覧。"""
    keys = []
    for f in schema:
        if getattr(f, "kind", "") == "date_wareki":
            keys += [f"{f.id}_iso", f"{f.id}_era", f"{f.id}_year",
                     f"{f.id}_month", f"{f.id}_day"]
    # 診断名に当てた ICD（分類に使えるよう、西暦などと同じ末尾にまとめる）
    for f in schema:
        if f.id.startswith("diagnosis") and f.id.endswith("_name"):
            keys += [f"{f.id}_icd10", f"{f.id}_tokutei"]
    keys += ["age_computed", "age_written", "age_matches"]
    return keys


def derived_labels(schema) -> Dict[str, str]:
    """CSV の2行目に出す日本語の見出し。"""
    labels = {}
    for f in schema:
        if getattr(f, "kind", "") == "date_wareki":
            labels[f"{f.id}_iso"] = f"{f.label}（西暦）"
            labels[f"{f.id}_era"] = f"{f.label}（元号）"
            labels[f"{f.id}_year"] = f"{f.label}（和暦年）"
            labels[f"{f.id}_month"] = f"{f.label}（月）"
            labels[f"{f.id}_day"] = f"{f.label}（日）"
    for f in schema:
        if f.id.startswith("diagnosis") and f.id.endswith("_name"):
            labels[f"{f.id}_icd10"] = f"{f.label}（ICD10）"
            labels[f"{f.id}_tokutei"] = f"{f.label}（特定疾病）"
    labels["age_computed"] = "年齢（生年月日から計算）"
    labels["age_written"] = "年齢（様式の記載）"
    labels["age_matches"] = "年齢の一致"
    return labels
