# -*- coding: utf-8 -*-
"""医療辞書による OCR 結果の補正と入力候補の提示。

OCR（特に日本語手書き）は誤りが多いため、読み取り結果を辞書に照合して
  - 十分近ければ辞書の正式表記に置き換える
  - 近い候補を並べて確認画面で選ばせる
という運用で精度を補う。LLM は使わない。
"""
import json
import os
import re
import unicodedata

from .kanji_norm import clean_ocr, normalize_variants
from dataclasses import dataclass, field as dc_field
from typing import Dict, List, Optional, Tuple

DICT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "dict")

# 辞書に十分近ければ自動採用するしきい値
AUTO_ADOPT = 0.72
# 候補として提示する下限
SUGGEST_MIN = 0.34
MAX_CANDIDATES = 8


def normalize(s: str) -> str:
    """全角半角・空白・記号のゆれを吸収する。"""
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = normalize_variants(s)
    s = s.replace("ヶ", "ケ").replace("ヵ", "カ")
    s = re.sub(r"[\s　・･,、。\.\-‐－―ー—_/\\()（）\[\]「」【】:：;；'\"]+", "", s)
    return s.lower()


def _bigrams(s: str) -> set:
    if len(s) < 2:
        return {s} if s else set()
    return {s[i:i + 2] for i in range(len(s) - 1)}


def _levenshtein(a: str, b: str) -> int:
    """編集距離。OCR の誤りは1文字置換が多いため、この指標がよく効く。"""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _partial_similarity(query: str, term: str) -> float:
    """辞書語と読み取り結果を、位置をずらしながら照合する。

    OCR 結果には「（保存期）」のような余分な文字が付くことが多いので、
    全体一致ではなく、短い方と同じ長さの窓を滑らせて最も近い位置で評価する。

    向きによって扱いを変える。
      - 辞書語が読み取り結果に含まれる（読み取り側に飾りが付いている）… そのまま
      - 読み取り結果が辞書語の一部でしかない（辞書語の方が限定的）… 上限をかける
    """
    if not query or not term:
        return 0.0
    if len(term) > len(query):
        # 辞書語の方が長い＝読み取れた内容は辞書語の一部でしかない。
        # 窓をずらして一致させると「骨折」が「圧迫骨折」に化けるので、
        # 全体の編集距離で見て「足りない文字がどれだけあるか」を評価する。
        #   骨粗症 → 骨粗鬆症  : 1文字不足 / 4文字 = 0.75（採用しうる）
        #   骨折   → 圧迫骨折  : 2文字不足 / 4文字 = 0.50（候補どまり）
        #   糖尿病 → 糖尿病性腎症: 3文字不足 / 6文字 = 0.50（候補どまり）
        d = _levenshtein(query, term)
        return max(0.0, 1.0 - d / len(term))

    # 読み取り側の方が長い（「（保存期）」のような飾りが付いている）場合は、
    # 辞書語と同じ長さの窓を滑らせて最も近い位置で評価する。
    n, m = len(query), len(term)
    best = 0.0
    for start in range(0, n - m + 1):
        for width in {m, min(m + 2, n - start)}:
            window = query[start:start + width]
            d = _levenshtein(window, term)
            best = max(best, 1.0 - d / max(len(window), m))
            if best >= 1.0:
                return 1.0
    return max(0.0, best)


# 辞書語が読み取り結果にそのまま含まれていて、しかもこれより短い場合は、
# 置き換えると情報が減るだけなので採用しない
SHORTEN_RATIO = 0.70


def _is_shortening(text: str, term: str) -> bool:
    """辞書語で置き換えると内容が削られてしまう関係か。"""
    nt, nb = normalize(text), normalize(term)
    if not nt or not nb or nb not in nt:
        return False
    return len(nb) < len(nt) * SHORTEN_RATIO


def similarity(a: str, b: str) -> float:
    """OCR 結果と辞書語の類似度 0..1。

    2-gram の Dice 係数と、編集距離による部分一致の大きい方を採る。
    Dice だけでは「骨粗葵症」と「骨粗鬆症」のような1文字違いを取り逃す。
    """
    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    ga, gb = _bigrams(na), _bigrams(nb)
    dice = 2 * len(ga & gb) / (len(ga) + len(gb)) if (ga or gb) else 0.0
    # 辞書語が読み取り結果に含まれている場合だけ加点する。
    # 逆（読み取りが辞書語の一部）は、書かれていない診断を作り出す恐れがあるので加点しない。
    if nb in na:
        dice = max(dice, 0.55 + 0.35 * len(nb) / max(len(na), 1))
    # 1文字違いを拾うための編集距離ベースの部分一致
    partial = _partial_similarity(na, nb)
    return round(max(dice, partial), 4)


@dataclass
class Entry:
    name: str
    icd10: str = ""
    tokutei: bool = False
    extra: dict = dc_field(default_factory=dict)


@dataclass
class Lexicon:
    key: str
    label: str
    entries: List[Entry]

    def search(self, query: str, limit: int = MAX_CANDIDATES,
               min_score: float = SUGGEST_MIN) -> List[Tuple[Entry, float]]:
        if not query:
            return []
        scored = [(e, similarity(query, e.name)) for e in self.entries]
        scored = [(e, s) for e, s in scored if s >= min_score]
        # 特定疾病は同点なら優先する
        scored.sort(key=lambda t: (-t[1], not t[0].tokutei, len(t[0].name)))
        return scored[:limit]

    def prefix(self, query: str, limit: int = MAX_CANDIDATES) -> List[Entry]:
        """入力補完用の前方一致検索。"""
        q = normalize(query)
        if not q:
            return self.entries[:limit]
        starts = [e for e in self.entries if normalize(e.name).startswith(q)]
        contains = [e for e in self.entries
                    if e not in starts and q in normalize(e.name)]
        return (starts + contains)[:limit]


class Dictionaries:
    def __init__(self, directory: str = DICT_DIR):
        self.directory = directory
        self.lexicons: Dict[str, Lexicon] = {}
        self.field_map: Dict[str, str] = {}
        self.load()

    def load(self) -> None:
        if not os.path.isdir(self.directory):
            return
        fm = os.path.join(self.directory, "field_map.json")
        if os.path.exists(fm):
            with open(fm, encoding="utf-8") as fp:
                self.field_map = json.load(fp)
        for path in sorted(os.listdir(self.directory)):
            if not path.endswith(".json") or path == "field_map.json":
                continue
            key = path[:-5]
            with open(os.path.join(self.directory, path), encoding="utf-8") as fp:
                raw = json.load(fp)
            entries = [Entry(name=e["name"], icd10=e.get("icd10", ""),
                             tokutei=bool(e.get("tokutei")),
                             extra={k: v for k, v in e.items()
                                    if k not in ("name", "icd10", "tokutei")})
                       for e in raw.get("entries", [])]
            self.lexicons[key] = Lexicon(key=key, label=raw.get("label", key),
                                         entries=entries)

    def strip_boilerplate(self, text: str, threshold: float = 0.80) -> str:
        """様式に印刷されている文言を読み取り結果から取り除く。

        テキスト欄の枠が説明文に食い込むと OCR がそれを拾ってしまうため、
        行ごとに定型文と照合して、**その定型文とほぼ同じ長さで十分似ている**
        場合だけ捨てる。

        以前は「定型文のどこかに含まれていれば捨てる」としていたが、
        それでは『認知症』『骨折』『がん』のような正しい記入内容まで
        消えてしまった（定型文の中にその語が出てくるため）。
        いまは長さの近さも条件に入れ、部分一致では捨てない。
        """
        lex = self.lexicons.get("boilerplate")
        if lex is None or not text:
            return text
        entries = [(e, normalize(e.name)) for e in lex.entries]
        kept = []
        for line in text.splitlines():
            n = normalize(line)
            if not n:
                continue
            drop = False
            for e, en in entries:
                if not en:
                    continue
                # 定型文と同程度の長さでなければ、記入内容とみなして残す
                ratio = min(len(n), len(en)) / max(len(n), len(en))
                if ratio < 0.70:
                    continue
                if n == en or similarity(line, e.name) >= threshold:
                    drop = True
                    break
            if not drop:
                kept.append(line)
        return "\n".join(kept).strip()

    def for_field(self, field_id: str) -> Optional[Lexicon]:
        key = self.field_map.get(field_id)
        return self.lexicons.get(key) if key else None

    def correct(self, field, text: str, base_confidence: float
                ) -> Tuple[str, float, List[dict]]:
        """OCR 結果を辞書で補正し、(採用値, 確信度, 候補一覧) を返す。"""
        text = self.strip_boilerplate(clean_ocr(text))
        lex = self.for_field(field.id)
        if lex is None or not text:
            return text, base_confidence, []

        hits = lex.search(text)
        candidates = [dict(value=e.name, score=s, icd10=e.icd10, tokutei=e.tokutei)
                      for e, s in hits]
        if not hits:
            # 辞書に無い＝読み違いの可能性が高いので確信度を下げる
            return text, round(base_confidence * 0.7, 3), []

        # そのものが辞書にあるなら、一致度の順に関わらずそれを採る
        exact = next((e for e, _ in hits if normalize(e.name) == normalize(text)), None)
        if exact is not None:
            return exact.name, round(min(1.0, base_confidence + 0.20), 3), candidates
        best, score = hits[0]
        if _is_shortening(text, best.name):
            # 読み取れた文字列の一部を辞書語がそのまま含んでいるだけの場合は
            # 置き換えない。置き換えると情報が減る。
            # 例: 『1 筑波記念病院記』→『病院』、『右大腿骨骨折』→『骨折』
            return text, round(base_confidence * 0.75, 3), candidates
        if score >= AUTO_ADOPT:
            # 辞書の正式表記を採用し、確信度は一致度との折衷にする
            conf = round(min(0.95, (base_confidence * 0.5 + score * 0.5)), 3)
            return best.name, conf, candidates
        return text, round(base_confidence * 0.75, 3), candidates

    def suggest(self, field_id: str, query: str, limit: int = MAX_CANDIDATES
                ) -> List[dict]:
        """確認画面の入力補完用。"""
        lex = self.lexicons.get(self.field_map.get(field_id, ""))
        if lex is None:
            return []
        return [dict(value=e.name, icd10=e.icd10, tokutei=e.tokutei)
                for e in lex.prefix(query, limit)]


_CACHE: Optional[Dictionaries] = None


def DEFAULT_DICTIONARIES() -> Dictionaries:
    global _CACHE
    if _CACHE is None:
        _CACHE = Dictionaries()
    return _CACHE
