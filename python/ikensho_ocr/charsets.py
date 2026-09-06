# -*- coding: utf-8 -*-
"""欄ごとの文字種ヒント。

日付・年齢・電話番号のように書かれる文字が決まっている欄は、
候補文字を絞るだけで OCR の精度が大きく上がる。
tesseract では whitelist として渡し、それ以外のエンジンでは後処理で使う。
"""
KATAKANA = "".join(chr(c) for c in range(0x30A1, 0x30F7))

CHARSETS = {
    "digits":  "0123456789",
    "decimal": "0123456789.",
    # 元号は様式で決まっている（印刷済み、または別項目の丸囲み）ので、
    # 日付欄では数字だけを読む。元号を候補に入れると誤読の元になる。
    "date_digits": "0123456789年月日頃 ",
    "wareki":  "0123456789年月日頃明治大正昭和平成令和 ",
    "postal":  "0123456789-〒 ",
    "phone":   "0123456789()-  ",
    "kana":    KATAKANA + "ー・ 　",
}


def whitelist(name: str) -> str:
    return CHARSETS.get(name or "", "")


def filter_text(text: str, name: str) -> str:
    """指定の文字種に含まれない文字を落とす。"""
    allowed = CHARSETS.get(name or "")
    if not allowed or not text:
        return text
    keep = set(allowed) | {"\n"}
    out = "".join(ch for ch in text if ch in keep)
    return " ".join(out.split()) if name != "kana" else out.strip()
