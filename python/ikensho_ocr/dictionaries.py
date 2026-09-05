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


def similarity(a: str, b: str) -> float:
    """Dice 係数（2-gram）と部分一致を組み合わせた類似度 0..1。"""
    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    ga, gb = _bigrams(na), _bigrams(nb)
    dice = 2 * len(ga & gb) / (len(ga) + len(gb)) if (ga or gb) else 0.0
    # OCR は文字が欠けやすいので、包含関係には加点する
    if na in nb or nb in na:
        dice = max(dice, 0.55 + 0.35 * min(len(na), len(nb)) / max(len(na), len(nb)))
    return round(dice, 4)


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

    def strip_boilerplate(self, text: str, threshold: float = 0.62) -> str:
        """様式に印刷されている文言を読み取り結果から取り除く。

        テキスト欄の枠が説明文に食い込むと OCR がそれを拾ってしまうため、
        行ごとに定型文と照合して十分似ていれば捨てる。
        """
        lex = self.lexicons.get("boilerplate")
        if lex is None or not text:
            return text
        kept = []
        for line in text.splitlines():
            n = normalize(line)
            if not n:
                continue
            if len(n) < 4:
                # 「記入）」のような短い切れ端も定型文の一部なら捨てる
                if any(n in normalize(e.name) for e in lex.entries):
                    continue
                kept.append(line)
                continue
            if not lex.search(line, limit=1, min_score=threshold):
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

        best, score = hits[0]
        if score >= 0.999:
            return best.name, round(min(1.0, base_confidence + 0.20), 3), candidates
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
