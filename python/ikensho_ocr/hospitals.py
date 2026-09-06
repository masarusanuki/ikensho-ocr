# -*- coding: utf-8 -*-
"""医療機関の一覧（厚生労働省 地方厚生局の保険医療機関一覧）との照合。

医療機関名は「〇〇病院」「〇〇クリニック」「〇〇医院」のように語尾が決まっており、
OCR が名前の一部しか読めなくても（`病院` だけ、`生ん愛和総合病院` など）、
所在地から都道府県を絞れば一覧から引き当てられることが多い。

一覧は `dict/hospitals/<都道府県>.json`（`tools/fetch_hospitals.py` で取得）。
無い都道府県では何もしない。
"""
import json
import os
import re
from typing import Dict, List, Optional

from .dictionaries import normalize, similarity

DICT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "dict", "hospitals")

# 一覧から採用してよいと判断する一致度
ADOPT = 0.85
# 候補として確認画面に出す下限
SUGGEST = 0.55
# 名前が短すぎると何にでも当たるので、この文字数未満は照合しない
MIN_QUERY = 3

_PREFS = [
    "北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県",
    "茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県",
    "新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県", "岐阜県",
    "静岡県", "愛知県", "三重県", "滋賀県", "京都府", "大阪府", "兵庫県",
    "奈良県", "和歌山県", "鳥取県", "島根県", "岡山県", "広島県", "山口県",
    "徳島県", "香川県", "愛媛県", "高知県", "福岡県", "佐賀県", "長崎県",
    "熊本県", "大分県", "宮崎県", "鹿児島県", "沖縄県",
]

_cache: Dict[str, List[dict]] = {}

# 一覧の正式名称には「医療法人社団 常仁会 牛久愛和総合病院」のように
# 開設者の名称が前に付く。意見書には施設名しか書かれないことが多いので、
# 前置きを外した「施設名だけ」とも突き合わせる。
_CORP = re.compile(
    r"^(?:特定|社会|地方独立行政|独立行政|国立研究開発|国立大学|公立大学|学校|社会福祉|"
    r"公益財団|公益社団|一般財団|一般社団|医療|宗教|農業協同組合|消費生活協同組合)?"
    r"(?:法人)?(?:社団|財団)?"
)


# 施設名の語尾。これで終わらない切れ端は施設名として扱わない。
# （`アグリホームクリニック つくば` の `つくば` だけを取ると、
#   `つくばセントラル病院` に一致度1.0で当たってしまう）
FACILITY_TAIL = ("病院", "医院", "クリニック", "ｸﾘﾆｯｸ", "診療所", "センター",
                 "医療センター", "歯科", "内科", "外科", "眼科", "皮膚科",
                 "産科", "婦人科", "整形外科", "小児科", "耳鼻咽喉科", "薬局")
# 切れ端が短すぎると何にでも当たるので、この文字数未満は使わない
MIN_CORE = 4


def core_names(name: str) -> List[str]:
    """突き合わせに使う名前の候補（正式名称と、開設者の前置きを外したもの）。"""
    out = [name]
    parts = [p for p in re.split(r"[\s\u3000]+", name) if p]
    for i in range(1, len(parts)):
        cand = "".join(parts[i:])
        # 施設名として成立するものだけ（`つくば` のような切れ端は使わない）
        if len(cand) >= MIN_CORE and cand.endswith(FACILITY_TAIL):
            out.append(cand)
    if len(parts) > 1:
        head = _CORP.sub("", parts[0])
        if head and head != parts[0]:
            cand = "".join([head] + parts[1:])
            if len(cand) >= MIN_CORE:
                out.append(cand)
    return out


def query_forms(text: str) -> List[str]:
    """読み取った文字列から、照合に使う形を作る。

    OCR は前後に余計な字を拾いやすい（`4 筐波記念病院`、`土浦協同病院時`）。
    施設名の語尾（病院・クリニックなど）で切り、前の記号や数字を落とした形も試す。
    """
    out = [text]
    n = text.strip()
    # 語尾までで切る（最後に現れるものを使う）
    cut = -1
    for tail in FACILITY_TAIL:
        i = n.rfind(tail)
        if i >= 0:
            cut = max(cut, i + len(tail))
    if cut > 0:
        n = n[:cut]
    # 先頭の数字・記号・空白を落とす
    n = re.sub(r"^[\s\u30000-9０-９.,、。・\-ー―_|｜]+", "", n)
    n = n.strip()
    if n and n != text:
        out.append(n)
    return out


def match_score(query: str, name: str) -> float:
    """OCR で読めた名前と、一覧の正式名称との一致度。

    切れ端が読み取り結果に丸ごと含まれるだけで満点になるのを避けるため、
    読み取り結果より極端に短い候補は使わない。
    """
    q = normalize(query)
    best = 0.0
    for c in core_names(name):
        if len(normalize(c)) < max(MIN_CORE, len(q) * 0.5):
            continue
        best = max(best, similarity(query, c))
    return best


def available() -> bool:
    return os.path.isdir(DICT_DIR) and bool(prefectures())


def prefectures() -> List[str]:
    """一覧を持っている都道府県。"""
    try:
        with open(os.path.join(DICT_DIR, "index.json"), encoding="utf-8") as fh:
            return [p["pref"] for p in json.load(fh).get("prefectures", [])]
    except Exception:
        return []


def guess_pref(*texts: str) -> Optional[str]:
    """所在地などの文字列から都道府県を推測する。"""
    for text in texts:
        if not text:
            continue
        n = normalize(text)
        for pref in _PREFS:
            if normalize(pref) in n:
                return pref
        # 「茨城」のように「県」が落ちている場合
        for pref in _PREFS:
            if normalize(pref[:-1]) and normalize(pref[:-1]) in n:
                return pref
    return None


def load(pref: str) -> List[dict]:
    if pref in _cache:
        return _cache[pref]
    path = os.path.join(DICT_DIR, f"{pref}.json")
    try:
        with open(path, encoding="utf-8") as fh:
            entries = json.load(fh).get("entries", [])
    except Exception:
        entries = []
    _cache[pref] = entries
    return entries


def find(name: str, pref: str, limit: int = 5) -> List[dict]:
    """名前が近い医療機関を、一致度の高い順に返す。"""
    entries = load(pref)
    forms = query_forms(name)
    if not entries or max(len(normalize(f)) for f in forms) < MIN_QUERY:
        return []
    scored = []
    for e in entries:
        s = max(match_score(q, e.get("name", "")) for q in forms)
        if s >= SUGGEST:
            scored.append((s, e))
    scored.sort(key=lambda x: (-x[0], len(x[1].get("name", ""))))
    return [dict(e, score=round(s, 3)) for s, e in scored[:limit]]
