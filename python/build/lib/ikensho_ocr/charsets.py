# -*- coding: utf-8 -*-
"""欄ごとの文字種ヒント。

日付・年齢・電話番号のように書かれる文字が決まっている欄は、
候補文字を絞るだけで OCR の精度が大きく上がる。
tesseract では whitelist として渡し、それ以外のエンジンでは後処理で使う。
"""
import re

KATAKANA = "".join(chr(c) for c in range(0x30A1, 0x30F7))
# **ひらがなも含める。** 様式の欄は「ふりがな」なので、書かれるのは
# ひらがなが普通（正解データ100通すべてがひらがな）。
# カタカナだけを許していたため、読めていても全部捨てて空にしていた
HIRAGANA = "".join(chr(c) for c in range(0x3041, 0x3097))

CHARSETS = {
    "digits":  "0123456789",
    "decimal": "0123456789.",
    # 元号は様式で決まっている（印刷済み、または別項目の丸囲み）ので、
    # 日付欄では数字だけを読む。元号を候補に入れると誤読の元になる。
    "date_digits": "0123456789年月日頃 ",
    "wareki":  "0123456789年月日頃明治大正昭和平成令和 ",
    "postal":  "0123456789-〒 ",
    # 電話番号は数字とハイフンだけ。様式に印刷された「（ ）」は市外局番の枠なので
    # 読み取り結果には残さない（後段で 029-873-3111 の形に整える）。
    "phone":   "0123456789- ",
    "kana":    HIRAGANA + KATAKANA + "ー゛゜・ 　",
}


def whitelist(name: str) -> str:
    return CHARSETS.get(name or "", "")


def normalize_phone(text: str) -> str:
    """電話番号を「029-873-3111」の形に整える。

    様式では市外局番が「（ ）」で囲まれているが、番号としては不要なので外す。
    区切りのハイフンはそのまま残す。
    """
    if not text:
        return ""
    parts = [p for p in re.split(r"[^0-9]+", text) if p]
    if not parts:
        return ""
    return "-".join(parts)


def filter_text(text: str, name: str) -> str:
    """指定の文字種に含まれない文字を落とす。"""
    allowed = CHARSETS.get(name or "")
    if not allowed or not text:
        return text
    if name == "phone":
        return normalize_phone(text)
    if name == "postal":
        digits = "".join(ch for ch in text if ch.isdigit())
        return f"{digits[:3]}-{digits[3:7]}" if len(digits) >= 7 else digits
    keep = set(allowed) | {"\n"}
    out = "".join(ch for ch in text if ch in keep)
    return " ".join(out.split()) if name != "kana" else out.strip()
