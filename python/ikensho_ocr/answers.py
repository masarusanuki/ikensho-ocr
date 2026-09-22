# -*- coding: utf-8 -*-
"""欄の答えを「人が読む形」にそろえる。

出力は JSON・CSV・Markdown の3通りあるが、**同じ欄が出力ごとに違う答えに
見えてはいけない**。読み方を決めるのはこのモジュール1か所だけにして、
どの出力もここを通す。

**選択肢に付いている記入欄。** 様式には「その他（　　　）」のように、
印だけでは中身の分からない選択肢がある。診療科がその代表で、
13個の選択肢に収まらない科は「その他」に名前が書かれる。

  - 「その他」で始まる選択肢 … 言葉に中身が無いので、**書かれた名前で置き換える**
    （`その他` → `循環器内科`）
  - それ以外 … 言葉に意味があるので、**括弧で足す**
    （`血圧` → `血圧（140/90 に注意）`）

どの選択肢にどの記入欄が付いているかは項目定義の `option_texts` にある
（`tools/form_definition.py` が正典）。
"""
from typing import Any, Dict, List, Optional

# 言葉に中身が無く、記入欄の内容で置き換える選択肢
REPLACE_PREFIX = "その他"
# flag 型（単独の□）で、印が付いたときの鍵
FLAG_KEY = "該当"


def _text_of(fields: Dict[str, dict], fid: Optional[str]) -> str:
    """付属の記入欄に読めた文字。空欄・未読は空文字。"""
    if not fid:
        return ""
    e = fields.get(fid) or {}
    v = e.get("value")
    if v is None or v is False:
        return ""
    return str(v).strip()


def decorate(word: str, text: str) -> str:
    """選択肢の言葉に、付属の記入欄の中身を反映した言葉を返す。"""
    if not text:
        return word
    if str(word).startswith(REPLACE_PREFIX):
        return text
    return f"{word}（{text}）"


def option_words(fields: Dict[str, dict], schema, f) -> List[str]:
    """その欄の選択肢を、付属の記入欄まで含めた言葉で並べる。"""
    e = fields.get(f.id) or {}
    words = e.get("option_words")
    if not (isinstance(words, list) and len(words) == len(f.options or [])):
        words = [str(o) for o in (f.options or [])]
    links = f.option_texts or {}
    out = []
    for base, word in zip(f.options or [], words):
        out.append(decorate(word, _text_of(fields, links.get(str(base)))))
    return out


def resolve(fields: Dict[str, dict], schema, f) -> Any:
    """その欄の答えを、人が読む形で返す。

    choice/multi は選択肢の言葉、flag は付属欄があればその中身、
    それ以外（文字・日付）は読めた値をそのまま返す。
    """
    e = fields.get(f.id)
    if e is None:
        return None
    value = e.get("value")
    links = f.option_texts or {}

    if f.type == "flag":
        if not value:
            return value
        text = _text_of(fields, links.get(FLAG_KEY))
        return f"{FLAG_KEY}（{text}）" if text else value

    if not f.options:
        return value

    # 読み取った値は**実物の言葉**に置き換え済みなので、
    # 定義の選択肢と読んだ言葉の両方から、付属欄の相手を引けるようにする
    read = option_words(fields, schema, f)
    plain = [str(o) for o in f.options]
    table = {}
    src = e.get("option_words")
    if isinstance(src, list) and len(src) == len(plain):
        for base, word, done in zip(plain, src, read):
            table[str(word)] = done
            table[base] = done
    else:
        for base, done in zip(plain, read):
            table[base] = done

    if isinstance(value, list):
        return [table.get(str(v), str(v)) for v in value]
    if isinstance(value, str):
        return table.get(value, value)
    return value


def used_text_fields(schema) -> Dict[str, str]:
    """選択肢に付いている記入欄の一覧（欄id → 付いている選択肢の欄id）。

    答えの中に取り込んだ欄を、出力の別の場所で二重に出さないため。
    """
    out: Dict[str, str] = {}
    for f in schema:
        for fid in (f.option_texts or {}).values():
            out[str(fid)] = f.id
    return out
