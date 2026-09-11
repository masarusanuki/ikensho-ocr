# -*- coding: utf-8 -*-
"""OCR 後の日本語チェックと誤字訂正。

三段構えにしている。
  1. 文字レベルの訂正（規則ベース・常時実行）
     OCR がよく取り違える字（力/カ、口/ロ、末/未 など）を、
     前後の文字種を見て機械的に直す。誤りが混入しないよう、
     「明らかにこちらしかあり得ない」場合だけ直す。
  2. 日本語としての妥当性チェック（常時実行）
     文字種の並び・記号の混入・未知語の割合から、日本語として
     成立しているかを数値にする。低ければ確信度を下げて要確認にする。
  3. 文章の校正（任意・LLM）
     経過や特記事項のような自由記述は、辞書照合が効かない。
     小型LLMに校正させるが、元の文から大きく変わった場合は棄却する。
"""
import re
import unicodedata
from dataclasses import dataclass, field as dc_field
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# 1. 文字レベルの訂正
# ---------------------------------------------------------------------------

HIRAGANA = r"ぁ-ゟ"
KATAKANA = r"ァ-ヿ"
KANJI = r"㐀-鿿豈-﫿"
JP = HIRAGANA + KATAKANA + KANJI

# 「日本語の文字に挟まれていたら、こちらが正しい」という置換。
# 文脈を見ずに一律置換すると別の誤りを生むため、必ず前後条件を付ける。
CONTEXT_FIXES: List[Tuple[str, str, str]] = [
    # (説明, 正規表現, 置換後)
    ("カタカナのカを漢字の力と誤認", rf"(?<=[{KATAKANA}])力(?=[{KATAKANA}])", "カ"),
    ("カタカナのロを漢字の口と誤認", rf"(?<=[{KATAKANA}])口(?=[{KATAKANA}])", "ロ"),
    ("カタカナのニを漢字の二と誤認", rf"(?<=[{KATAKANA}])二(?=[{KATAKANA}])", "ニ"),
    ("カタカナのヘをひらがなのへと誤認", rf"(?<=[{KATAKANA}])へ(?=[{KATAKANA}])", "ヘ"),
    ("ひらがなのへをカタカナのヘと誤認", rf"(?<=[{HIRAGANA}])ヘ(?=[{HIRAGANA}])", "へ"),
    ("長音記号を漢数字の一と誤認", rf"(?<=[{KATAKANA}])一(?=[{KATAKANA}])", "ー"),
    ("長音記号をハイフンと誤認", rf"(?<=[{KATAKANA}])[-−–—](?=[{KATAKANA}])", "ー"),
]

# 医療・介護文書でよく出る誤字。左が誤り、右が正しい表記。
# OCR の誤認と、もとの文書の誤変換の両方を対象にする。
WORD_FIXES: Dict[str, str] = {
    "遍数回": "週数回", "遍1回": "週1回", "遍2回": "週2回", "遍3回": "週3回",
    "臥床": "臥床", "山床": "臥床", "卧床": "臥床",
    "褥創": "褥瘡", "褥そう": "褥瘡", "褥瘖": "褥瘡",
    "嚥化": "嚥下", "臙下": "嚥下", "醸下": "嚥下",
    "誤嚥性肺災": "誤嚥性肺炎", "肺災": "肺炎",
    "認知庄": "認知症", "認知痘": "認知症",
    "麻庫": "麻痺", "麻ひ": "麻痺", "麻痴": "麻痺",
    "拘縮": "拘縮", "抅縮": "拘縮",
    "徘個": "徘徊", "俳徊": "徘徊", "徘廻": "徘徊",
    "見守リ": "見守り", "見寺り": "見守り",
    "介謹": "介護", "介穫": "介護", "介渡": "介護",
    "訪間": "訪問", "訪聞": "訪問",
    "自立度": "自立度", "白立度": "自立度", "白立": "自立",
    "車いす": "車いす", "車イス": "車いす", "車椅子": "車椅子",
    "リハビリ": "リハビリ", "リハピリ": "リハビリ", "リハビリテーシヨン": "リハビリテーション",
    "糖尿病": "糖尿病", "糠尿病": "糖尿病",
    "高血圧症": "高血圧症", "高血庄症": "高血圧症", "高血庄": "高血圧",
    "骨折": "骨折", "骨析": "骨折",
    "内服": "内服", "内脹": "内服",
    "服薬": "服薬", "脹薬": "服薬",
    "血圧測定": "血圧測定", "血庄測定": "血圧測定",
    "食事摂取": "食事摂取", "食事撮取": "食事摂取",
    "排泄": "排泄", "排洩": "排泄",
    "更衣": "更衣", "更依": "更衣",
    "入浴": "入浴", "人浴": "入浴",
    "独居": "独居", "狛居": "独居",
    "家族": "家族", "冢族": "家族",
    "転倒": "転倒", "頼倒": "転倒",
    "安定": "安定", "安走": "安定",
    "継続": "継続", "継絞": "継続",
    "投与": "投与", "投興": "投与",
    "経過": "経過", "経渦": "経過",
    "症状": "症状", "痘状": "症状",
    "治療": "治療", "治僚": "治療",
    "疼痛": "疼痛", "痺痛": "疼痛",
}

# 明らかにゴミな文字（OCR が罫線や汚れを拾ったもの）
NOISE_CHARS = "|｜!！\"'`^~*#$%&@={}<>\\"

# 日本語として妥当と認める文字
VALID_RE = re.compile(rf"[{JP}0-9０-９a-zA-Zａ-ｚＡ-Ｚ\s、。・（）()「」『』〔〕：:；;／/＋+－\-.,％%℃㎎㎏㎜㎝ー～〜]")


@dataclass
class Correction:
    before: str
    after: str
    reason: str


@dataclass
class ProofResult:
    text: str
    corrections: List[Correction] = dc_field(default_factory=list)
    japanese_score: float = 1.0     # 日本語として成立しているか 0..1
    note: str = ""

    @property
    def changed(self) -> bool:
        return bool(self.corrections)


def _strip_noise(text: str) -> Tuple[str, List[Correction]]:
    """罫線や汚れ由来の記号を落とす。"""
    fixes = []
    out = []
    for ch in text:
        if ch in NOISE_CHARS:
            fixes.append(Correction(ch, "", "記号として意味をなさないため削除"))
            continue
        out.append(ch)
    cleaned = re.sub(r"[ 　]{2,}", " ", "".join(out)).strip()
    # 行頭に残りがちな記号
    cleaned2 = re.sub(r"^[\s.,、。・:：;；\-ー_]+", "", cleaned)
    if cleaned2 != cleaned:
        fixes.append(Correction(cleaned[:len(cleaned) - len(cleaned2)], "",
                                "行頭の不要な記号を削除"))
    return cleaned2, fixes


def _apply_context_fixes(text: str) -> Tuple[str, List[Correction]]:
    fixes = []
    for reason, pattern, repl in CONTEXT_FIXES:
        def _sub(m):
            fixes.append(Correction(m.group(0), repl, reason))
            return repl
        text = re.sub(pattern, _sub, text)
    return text, fixes


def _apply_word_fixes(text: str) -> Tuple[str, List[Correction]]:
    fixes = []
    for wrong, right in WORD_FIXES.items():
        if wrong == right or wrong not in text:
            continue
        text = text.replace(wrong, right)
        fixes.append(Correction(wrong, right, "医療・介護文書でよくある誤字"))
    return text, fixes


def japanese_score(text: str) -> float:
    """日本語として成立している度合い 0..1。

    妥当な文字の割合と、日本語の文字がどれだけ含まれるかを見る。
    OCR が失敗した欄は記号やアルファベットの羅列になるので、この値が下がる。
    """
    t = (text or "").strip()
    if not t:
        return 1.0
    valid = sum(1 for ch in t if VALID_RE.match(ch))
    jp = sum(1 for ch in t if re.match(rf"[{JP}]", ch))
    digits = sum(1 for ch in t if ch.isdigit())
    ratio_valid = valid / len(t)
    # 数字だけの欄（年齢・電話など）は日本語が無くて当然
    if digits >= len(t) * 0.6:
        return round(ratio_valid, 3)
    ratio_jp = jp / max(len(t), 1)
    return round(min(1.0, ratio_valid * 0.6 + min(ratio_jp * 2.0, 1.0) * 0.4), 3)


def katakana_to_hiragana(text: str) -> str:
    """カタカナをひらがなに直す。長音符や記号はそのまま残す。"""
    out = []
    for ch in text or "":
        code = ord(ch)
        if 0x30A1 <= code <= 0x30F6:      # ァ〜ヶ
            out.append(chr(code - 0x60))
        else:
            out.append(ch)
    return "".join(out)


def to_furigana(text: str) -> Tuple[str, Optional[Correction]]:
    """ふりがな欄をひらがなに揃える。

    様式は「（ふりがな）」なのでひらがなが正だが、カタカナで書かれることも多い。
    直した場合は、何をしたか分かるように記録を返す。
    """
    t = (text or "").strip()
    if not t:
        return t, None
    converted = katakana_to_hiragana(t)
    if converted == t:
        return t, None
    return converted, Correction(t, converted,
                                 "様式は「ふりがな」なので、カタカナをひらがなに直しました")


def proofread_text(text: str, multiline: bool = False) -> ProofResult:
    """規則ベースの日本語チェックと誤字訂正。LLM は使わない。"""
    if not text or not text.strip():
        return ProofResult(text or "")
    original = text
    corrections: List[Correction] = []

    text = unicodedata.normalize("NFKC", text) if not multiline else text
    text, f = _strip_noise(text)
    corrections += f
    text, f = _apply_context_fixes(text)
    corrections += f
    text, f = _apply_word_fixes(text)
    corrections += f

    score = japanese_score(text)
    note = ""
    if score < 0.6:
        note = "日本語として読み取れていない可能性があります"
    return ProofResult(text=text if text else original, corrections=corrections,
                       japanese_score=score, note=note)


# ---------------------------------------------------------------------------
# 3. LLM による文章校正（任意）
# ---------------------------------------------------------------------------

PROOF_SYSTEM = (
    "あなたは日本語の医療文書の校正者です。"
    "与えられた文は、紙の書類をOCRで読み取ったものです。"
    "誤字・脱字・変換ミスだけを直し、校正後の文だけを出力します。"
    "書かれていない内容を足してはいけません。"
    "内容の言い換え・要約・敬語への変換もしてはいけません。"
    "直すところが無ければ、そのまま出力します。"
    "説明や前置きは書きません。"
)

# 校正で変わってよい文字数の上限（元の文に対する割合）
MAX_EDIT_RATIO = 0.25


def _edit_ratio(a: str, b: str) -> float:
    from .dictionaries import _levenshtein
    if not a and not b:
        return 0.0
    return _levenshtein(a, b) / max(len(a), len(b), 1)


def proofread_with_llm(assist, text: str, field_label: str) -> Optional[ProofResult]:
    """自由記述欄を小型LLMで校正する。

    元の文から大きく変わった場合は棄却する。LLM は書かれていない内容を
    作り出すことがあるため、「小さな直し」しか受け入れない。
    """
    if assist is None or not assist.available:
        return None
    t = (text or "").strip()
    if len(t) < 8:
        return None
    prompt = f"項目: {field_label}\n原文:\n{t}\n\n校正後:"
    out = assist.complete(PROOF_SYSTEM, prompt, max_tokens=min(512, len(t) * 3))
    if not out:
        return None
    out = out.strip().strip("「」\"'` ")
    if not out or out == t:
        return None
    ratio = _edit_ratio(t, out)
    if ratio > MAX_EDIT_RATIO:
        return None                     # 変わりすぎ＝作文された可能性
    if japanese_score(out) < japanese_score(t):
        return None                     # 日本語として悪化しているなら採らない
    return ProofResult(text=out,
                       corrections=[Correction(t[:24], out[:24], "LLMによる校正")],
                       japanese_score=japanese_score(out),
                       note="LLMが校正した結果です。原文と見比べて確認してください。")

# 小数1桁で書かれる欄の、ありえる範囲。
# 手書きの小さな小数点は読み落とされやすく、「152.5」が「1525」になる。
# 範囲から外れていて、小数点を入れると範囲に収まる場合だけ直す。
DECIMAL_RANGES = {
    "height_cm": (100.0, 220.0),
    "weight_kg": (20.0, 200.0),
}


def fix_decimal_point(field_id: str, text: str) -> Tuple[str, Optional[Correction]]:
    """読み落とされた小数点を戻す。

    身長「152.5」が「1525」と読まれることがある。**範囲で判断する**ので、
    「152」のように小数点なしでも筋の通る値はそのままにする。
    """
    lo, hi = DECIMAL_RANGES.get(field_id, (None, None))
    t = (text or "").strip()
    if lo is None or not t or not t.isdigit():
        return t, None
    try:
        value = float(t)
    except ValueError:
        return t, None
    if lo <= value <= hi:
        return t, None                    # そのままで筋が通る
    if len(t) < 2:
        return t, None
    fixed = f"{t[:-1]}.{t[-1]}"
    try:
        if not lo <= float(fixed) <= hi:
            return t, None                # 入れても筋が通らないなら触らない
    except ValueError:
        return t, None
    return fixed, Correction(t, fixed, reason="小数点が読めていないと判断しました")

# 医療機関名の前に書かれる法人名。「医療機関名」欄としては別物なので落とす。
#   医療法人社団 常仁会 牛久愛和総合病院 → 牛久愛和総合病院
# 「医療法人」で始まり、「〜会」までを法人名とみなす。
# 国立・県立・市立などは施設名の一部なので**落とさない**。
_CORPORATE = re.compile(
    r"^\s*(社会|特定)?医療法人\s*(社団|財団|社団法人|財団法人)?\s*"
    r"([^\s]{1,12}?(会|会館|協会))?\s*")


def strip_corporate(text: str) -> Tuple[str, Optional[Correction]]:
    """医療機関名の前に付いた法人名を落とす。

    落とした結果が短すぎる（施設名が残らない）場合は触らない。
    """
    t = (text or "").strip()
    if not t or "医療法人" not in t:
        return t, None
    m = _CORPORATE.match(t)
    if not m or not m.group(0).strip():
        return t, None
    rest = t[m.end():].strip()
    if len(rest) < 3:
        return t, None              # 施設名が残らないなら触らない
    return rest, Correction(t, rest, reason="法人名を落としました（医療機関名の欄）")
