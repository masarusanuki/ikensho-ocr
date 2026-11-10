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
# ICD コードを付けてよい一致度の下限。これ未満は「近い場所」とは言えない。
# 例: `起立性低血圧` に対する最有力が `貧血`（0.50）のような場合は付けない
ICD_MIN = 0.60


# 辞書語を当てても「捨ててよい」文字。記号・空白だけ。
# 「右」「両」「術後」「（保存期）」のような語は**捨ててはいけない**ので、
# 長さの比ではなく**何が捨てられるか**で判断する。
_DROPPABLE = re.compile(r"[\s　.,、。・:：;；!！?？'\"“”「」『』（）()\[\]【】/／\\|ー\-—–]+")


def _is_shortening(text: str, term: str) -> bool:
    """辞書語で置き換えると内容が削られてしまう関係か。

    以前は「辞書語が読み取り結果の7割未満の長さなら削られる」と見ていたが、
    `右大腿骨頸部骨折術後`（10文字）に `大腿骨頸部骨折`（7文字）を当てると
    比がちょうど 0.70 で判定を抜け、**「右」と「術後」が消えていた**。
    診療情報でこれは起こしてはいけない。

    そこで、辞書語を取り除いた**残りに意味のある文字があるか**で判断する。
    残りが記号・空白だけ（例: `高血圧症。` → `。`）なら、
    辞書の正式表記に直してよい。
    """
    nt, nb = normalize(text), normalize(term)
    if not nt or not nb or nb not in nt:
        return False
    rest = nt.replace(nb, "", 1)
    return bool(_DROPPABLE.sub("", rest))


# --- 形の似た字を同じものとして見る -------------------------------------
#
# 手書きの OCR は**部首を落とす・入れ替える**ことが多い。
#   慢→曼（忄が落ちる）  肺→柿（月が木に入れ替わる）  塞→業
# 「曼性閉業性柿疾氏」は、そのまま比べると「慢性閉塞性肺疾患」に半分しか
# 似ていない。形の似た字をひとまとめにしてから比べると、ぐっと近くなる。
#
# 組は dict/ocr_confusions.json（誤字表を作るのと同じもの）から作る。
_CANON: Optional[Dict[str, str]] = None
# そろえた後の1字違いを許す、語の最短の長さ
CANON_MIN_LEN = 6


def _canon_map() -> Dict[str, str]:
    """形の似た字の組を、代表の字への対応にする（つながった組はひとまとめ）。"""
    global _CANON
    if _CANON is not None:
        return _CANON
    path = os.path.join(DICT_DIR, "ocr_confusions.json")
    parent: Dict[str, str] = {}

    def find(c):
        while parent.get(c, c) != c:
            c = parent[c]
        return c

    try:
        with open(path, encoding="utf-8") as fp:
            raw = json.load(fp)
        for a, b in list(raw.get("pairs", [])) + list(raw.get("kana_pairs", [])):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb
    except Exception:
        pass
    _CANON = {c: find(c) for c in list(parent)}
    return _CANON


def canonical(s: str) -> str:
    """形の似た字を代表の字にそろえる。"""
    m = _canon_map()
    return "".join(m.get(c, c) for c in (s or ""))


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
    best = max(dice, partial)
    # 形の似た字をそろえてから比べ直す。**そろえた結果が完全に一致したときだけ**
    # 採る（部分的に似ているだけで加点すると、別の病名に寄ってしまう）
    if best < 0.95:
        ca, cb = canonical(na), canonical(nb)
        if ca == cb and ca:
            best = max(best, 0.90)
        # 長い病名なら、そろえた後に1字だけ違うのは同じ語とみなしてよい
        # （「慢性閉塞性肺疾氏」と「慢性閉塞性肺疾患」）。
        # 短い語では1字違いが別の語になるので、6字以上に限る
        elif min(len(ca), len(cb)) >= CANON_MIN_LEN and \
                abs(len(ca) - len(cb)) <= 1 and _levenshtein(ca, cb) <= 1:
            best = max(best, 0.85)
    return round(best, 4)


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
        # 同点なら**より詳しい（長い）辞書語**を先にする。
        # ICD は詳しいほど近い場所を指すので、`脳血管性認知症` には
        # `認知症(F03)` より `血管性認知症(F01.9)` を当てたい。
        # 以前は短い方を先にしていたため、粗いコードが選ばれていた。
        # 特定疾病は、同じ詳しさのときだけ優先する（介護保険の判定に関わる）。
        scored.sort(key=lambda t: (-t[1], -len(normalize(t[0].name)), not t[0].tokutei))
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
            # 辞書によって entries の形が違う。
            #   [{"name": ...}]        … 傷病名・市区町村など
            #   ["語", "語", ...]      … care_terms.json（誤字表の種）
            #   {"誤": "正", ...}      … word_fixes.json（語の対。辞書としては使わない）
            raw_entries = raw.get("entries") or []
            if isinstance(raw_entries, dict):
                raw_entries = []
            entries = []
            for e in raw_entries:
                if isinstance(e, str):
                    entries.append(Entry(name=e))
                    continue
                if not isinstance(e, dict) or not e.get("name"):
                    continue
                entries.append(Entry(name=e["name"], icd10=e.get("icd10", ""),
                                     tokutei=bool(e.get("tokutei")),
                                     extra={k: v for k, v in e.items()
                                            if k not in ("name", "icd10", "tokutei")}))
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

    def nearest_icd(self, field, text: str) -> Optional[dict]:
        """診断名に対して、ICD のいちばん近い場所を返す。

        候補は「詳しい（長い）辞書語が先」に並んでいるので、その先頭を使う。
        似ていないものに無理にコードを付けないよう、下限を設けている。
        """
        lex = self.for_field(field.id)
        if lex is None or not text:
            return None
        hits = lex.search(clean_ocr(text), limit=1)
        if not hits:
            return None
        entry, score = hits[0]
        if score < ICD_MIN or not entry.icd10:
            return None
        return dict(code=entry.icd10, name=entry.name, score=round(score, 4),
                    tokutei=bool(entry.tokutei),
                    exact=normalize(entry.name) == normalize(text))

    def suggest(self, field_id: str, query: str, limit: int = MAX_CANDIDATES
                ) -> List[dict]:
        """確認画面の入力補完用。"""
        lex = self.lexicons.get(self.field_map.get(field_id, ""))
        if lex is None:
            return []
        return [dict(value=e.name, icd10=e.icd10, tokutei=e.tokutei)
                for e in lex.prefix(query, limit)]


_CACHE: Optional[Dictionaries] = None


# --- 住所の先頭の都道府県をそろえる ---------------------------------------
#
# 住所欄の先頭には必ず都道府県が入る。読み崩れても、47個のどれかに寄せられる。
#
# **都道府県の名前だけで決めてはいけない。** 「天城県」は
# 茨城県とも宮城県とも1文字違いで、**どちらとも決まらない**。
# 後ろに続く市区町村から逆に決めると、ほぼ一意に決まる
# （1,914件のうち複数県にある名前は25件・1.3%だけ）。
#
# 市区町村でも決まらないときだけ、名前の近さで寄せる。
# それでも割れるときは**触らない**（間違った県に書き換える方が害が大きい）。

# 地名の異体字。**同じ場所を指すのに字が違う**ので、揃えてから突き合わせる。
# 「龍ケ崎市」は「竜ケ崎市」「龍ヶ崎市」「竜ヶ崎市」とも書かれる
PLACE_VARIANTS = str.maketrans({
    "竜": "龍", "ヶ": "ケ", "ガ": "ケ", "が": "ケ", "之": "ノ", "ノ": "ノ",
    "櫻": "桜", "澤": "沢", "瀧": "滝", "藝": "芸", "嶋": "島", "嶌": "島",
    "濱": "浜", "邊": "辺", "邉": "辺", "齋": "斎", "齊": "斉", "淺": "浅",
    "眞": "真", "德": "徳", "祿": "禄", "廣": "広", "區": "区", "縣": "県",
})


def _same_place(a: str, b: str) -> bool:
    """同じ地名か。異体字と送り仮名の揺れを吸収して比べる。"""
    return (a or "").translate(PLACE_VARIANTS) == (b or "").translate(PLACE_VARIANTS)


# 「○○県」まで取る。都・道・府・県のどれか
PREF_HEAD = re.compile(r"^\s*(.{2,4}?[都道府県])")
# 市区町村の切れ目
CITY_HEAD = re.compile(r"^(.{1,8}?[市区町村])")
# 都道府県の名前として寄せてよい近さ
PREF_MIN = 0.50
# 1位と2位がこれ以上離れていないと、決まらなかったとみなす
PREF_MARGIN = 0.08


def snap_prefecture(text: str, dicts: "Dictionaries") -> Tuple[str, Optional[str]]:
    """住所の先頭の都道府県を、一覧のどれかに寄せる。

    返り値は (直した住所, 何をしたかの説明)。直さなかったときは説明が None。
    """
    t = (text or "").strip()
    if not t:
        return text, None
    prefs = dicts.lexicons.get("prefectures")
    if prefs is None:
        return text, None
    names = [e.name for e in prefs.entries]

    m = PREF_HEAD.match(t)
    if not m:
        return text, None
    head, rest = m.group(1), t[m.end():]
    if head in names:
        return text, None          # すでに正しい

    # (1) 後ろの市区町村から決める。**これがいちばん確か**
    towns = dicts.lexicons.get("municipalities")
    if towns is not None:
        cm = CITY_HEAD.match(rest)
        if cm:
            city = cm.group(1)
            hit = {e.extra.get("pref") for e in towns.entries
                   if _same_place(e.name, city)}
            hit.discard(None)
            if len(hit) == 1:
                pref = hit.pop()
                if pref and pref != head:
                    return pref + rest, f"市区町村「{city}」から都道府県を直しました"
                return text, None

    # (2) 名前の近さで寄せる。1位と2位が競ったら触らない
    scored = sorted(((similarity(head, n), n) for n in names), reverse=True)
    if not scored or scored[0][0] < PREF_MIN:
        return text, None
    if len(scored) > 1 and scored[0][0] - scored[1][0] < PREF_MARGIN:
        return text, None          # どちらとも決まらない
    return scored[0][1] + rest, f"都道府県を一覧の「{scored[0][1]}」に寄せました"


# --- 診断名を ICD10 の病名に寄せる ----------------------------------------
#
# 読み崩れた診断名を、ICD10 の分類名に置き換える。
# ただし **書かれていた修飾は落とさない**。
# 「右大腿骨頸部骨折術後」を「大腿骨頸部骨折」にすると、
# 右なのか左なのか、術後なのかが消えてしまう。
# ICD の名前を採ったうえで、修飾を付け直す。
QUALIFY_PRE = ("右", "左", "両", "同")
QUALIFY_POST = ("術後", "後遺症", "の疑い", "疑い", "増悪", "再発", "の既往", "既往")


# ICD の名前が読みよりこの割合より短いなら、**大まかな名前**とみなして置き換えない。
# 「腰椎圧迫骨折」を「圧迫骨折」にすると部位が、「間質性肺炎」を「肺炎」に
# すると病気の種類が消える（実測で起きた）。
ICD_MIN_COVER = 0.75


def apply_icd_name(read: str, icd_name: str) -> str:
    """ICD の病名を採り、読みに付いていた修飾を戻す。

    ICD の名前の方が**大まかなとき**は置き換えない（読みのまま返す）。
    ICD のコードは呼び出し側で別に付くので、分類には使える。
    """
    read = (read or "").strip()
    name = (icd_name or "").strip()
    if not name:
        return read
    pre = next((q for q in QUALIFY_PRE if read.startswith(q)), "")
    post = next((q for q in QUALIFY_POST if read.endswith(q)), "")
    core = read[len(pre):len(read) - len(post) if post else len(read)]
    if core and len(name) < len(core) * ICD_MIN_COVER:
        return read          # ICD の方が大まかなので、詳しい読みを残す
    out = name
    if pre and not out.startswith(pre):
        out = pre + out
    if post and not out.endswith(post):
        out = out + post
    return out


def DEFAULT_DICTIONARIES() -> Dictionaries:
    global _CACHE
    if _CACHE is None:
        _CACHE = Dictionaries()
    return _CACHE
