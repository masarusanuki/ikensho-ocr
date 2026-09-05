# -*- coding: utf-8 -*-
"""匿名化加工済みデータ（研究用）の取り扱い。

研究用に配布される意見書は氏名欄が白抜き（黒塗り）されていることがある。
その場合は「読み取り失敗」ではなく「匿名化済み」として扱い、
住所・連絡先などの個人を特定しうる欄は「マスク済み」と表示する。
"""
from typing import Dict

ANONYMIZED = "匿名化済み"
MASKED = "マスク済み"


def apply(fields: Dict[str, dict], schema, force: bool = False) -> Dict[str, dict]:
    """匿名化データとして項目を書き換える。

    force=False のときは、氏名欄が空（白抜き）の場合だけ匿名化済みとして扱う。
    force=True（「匿名化加工済みデータ」を指定した場合）は、
    住所・連絡先なども一律でマスク済みにする。
    元の読み取り値は破棄するため、出力に個人情報が残らない。
    """
    for f in schema:
        pii = getattr(f, "pii", "")
        if not pii or f.id not in fields:
            continue
        e = fields[f.id]
        value = e.get("value")
        is_blank = value in (None, "") or (isinstance(value, str) and not value.strip())

        if pii == "name":
            if force or is_blank:
                e["value"] = ANONYMIZED
                e["raw"] = ""
                e["candidates"] = []
                e["confidence"] = 1.0
                e["level"] = "high"
                e["anonymized"] = True
        elif pii == "mask" and force:
            e["value"] = MASKED
            e["raw"] = ""
            e["candidates"] = []
            e["confidence"] = 1.0
            e["level"] = "high"
            e["anonymized"] = True
    return fields


def looks_anonymized(fields: Dict[str, dict], schema) -> bool:
    """氏名欄がすべて空なら、匿名化済みデータの可能性が高い。"""
    names = [f.id for f in schema if getattr(f, "pii", "") == "name"]
    if not names:
        return False
    return all(not (fields.get(n, {}).get("value") or "").strip()
               if isinstance(fields.get(n, {}).get("value"), str)
               else not fields.get(n, {}).get("value")
               for n in names)
