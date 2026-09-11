# -*- coding: utf-8 -*-
"""和暦の日付欄の解釈。

意見書の日付欄は「令和 7 年 3 月 20 日」のように、元号と数字が
決まった順に並ぶ。OCR の結果から年・月・日を取り出して部品に分け、
確認画面では**数字を埋めるだけ**で直せるようにする。
西暦も計算しておくと、集計や照合のときに扱いやすい。
"""
import re
import unicodedata
from typing import Dict, Optional

# 元号と、その元年に対応する西暦
ERAS = {
    "明治": 1868, "明": 1868, "M": 1868,
    "大正": 1912, "大": 1912, "T": 1912,
    "昭和": 1926, "昭": 1926, "S": 1926,
    "平成": 1989, "平": 1989, "H": 1989,
    "令和": 2019, "令": 2019, "R": 2019,
}
# 表示に使う正式表記
CANONICAL = {"明": "明治", "大": "大正", "昭": "昭和", "平": "平成", "令": "令和",
             "M": "明治", "T": "大正", "S": "昭和", "H": "平成", "R": "令和"}

ERA_PATTERN = re.compile(r"(明治|大正|昭和|平成|令和|明|大|昭|平|令)")


def canonical_era(era: Optional[str]) -> str:
    if not era:
        return ""
    era = unicodedata.normalize("NFKC", era).strip()
    return CANONICAL.get(era, era if era in ERAS else "")


def parse(text: str) -> Dict[str, Optional[int]]:
    """「令和 7 年 3 月 20 日」のような文字列を年・月・日に分ける。

    元号が書かれていればそれも返す。数字が足りなくても、
    取れたものだけ返す（欠けた分は確認画面で人が埋める）。
    """
    out: Dict[str, Optional[int]] = {"era": "", "year": None, "month": None, "day": None}
    if not text:
        return out
    t = unicodedata.normalize("NFKC", str(text))

    m = ERA_PATTERN.search(t)
    if m:
        out["era"] = canonical_era(m.group(1))
        t = t[m.end():]

    # 印刷されている「年」「月」「日」を区切りにして拾う。
    #
    # 「日」は欄のいちばん右に印刷されているため、読み取りの都合で
    # 落ちることがある（例: `12年3月4`）。そこで **「日」が無くても
    # 「月」より後の数字を日として拾う**。
    # 逆に読み取りが乱れて `8日年11月20` のように余分な字が挟まることもあるので、
    # 数字と区切り文字の間に少しの異物を許す。
    y = re.search(r"(\d+)\D{0,2}年", t)
    if y:
        out["year"] = int(y.group(1))
    after_year = t[y.end():] if y else t

    mo = re.search(r"(\d+)\D{0,2}月", after_year)
    if mo:
        out["month"] = int(mo.group(1))
    # 「月」の位置で切る。月の数字が読めなくても、その後ろは日として拾える
    mark = after_year.find("月")
    after_month = after_year[mark + 1:] if mark >= 0 else None

    if after_month is not None:
        d = re.search(r"(\d+)", after_month)       # 「日」が無くても拾う
        if d:
            out["day"] = int(d.group(1))
    else:
        d = re.search(r"(\d+)\D{0,2}日", t)
        if d:
            out["day"] = int(d.group(1))

    # 区切り文字が1つも読めなかった場合は、数字の並び順で拾う
    if out["year"] is None and out["month"] is None and out["day"] is None:
        nums = [int(n) for n in re.findall(r"\d{1,4}", t)]
        for key, val in zip(("year", "month", "day"), nums):
            out[key] = val

    # ありえない値は捨てる（読み間違いをそのまま通さない）。
    # 元号年なので、年は2桁までしか入らない
    if out["year"] is not None and not 1 <= out["year"] <= 99:
        out["year"] = None
    if out["month"] is not None and not 1 <= out["month"] <= 12:
        out["month"] = None
    if out["day"] is not None and not 1 <= out["day"] <= 31:
        out["day"] = None
    return out


def format_wareki(parts: Dict, with_era: bool = False) -> str:
    """部品から「7年3月20日」の形に戻す。空の部分は飛ばす。"""
    if not parts:
        return ""
    chunks = []
    if with_era and parts.get("era"):
        chunks.append(str(parts["era"]))
    for key, mark in (("year", "年"), ("month", "月"), ("day", "日")):
        v = parts.get(key)
        if v not in (None, ""):
            chunks.append(f"{v}{mark}")
    return "".join(chunks)


def to_gregorian(era: str, year: Optional[int], month: Optional[int],
                 day: Optional[int]) -> Optional[str]:
    """元号と和暦年から西暦の日付文字列を作る。判断できなければ None。"""
    base = ERAS.get(canonical_era(era)) or ERAS.get(era or "")
    if base is None or not year or year < 1:
        return None
    y = base + year - 1
    if not 1868 <= y <= 2200:
        return None
    if month and day:
        return f"{y:04d}-{month:02d}-{day:02d}"
    if month:
        return f"{y:04d}-{month:02d}"
    return f"{y:04d}"


def enrich(value: str, era: Optional[str] = None, fixed_era: bool = False) -> Dict:
    """読み取り値から、部品・整形済み文字列・西暦をまとめて作る。

    fixed_era=True のときは、本文中に元号らしき文字があっても無視して
    渡された元号を使う（様式に印刷されている場合など）。
    """
    parts = parse(value)
    if fixed_era and era:
        parts["era"] = canonical_era(era)
    elif era and not parts["era"]:
        parts["era"] = canonical_era(era)
    return dict(
        parts={k: parts[k] for k in ("year", "month", "day")},
        era=parts["era"],
        text=format_wareki(parts),
        gregorian=to_gregorian(parts["era"], parts["year"], parts["month"], parts["day"]),
    )
