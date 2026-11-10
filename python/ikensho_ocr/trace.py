# -*- coding: utf-8 -*-
"""どの欄を、どの仕組みで読んだのかを残す。

**「なぜこの値になったか」が追えないと、直しようがない。**
読み取りは何段も重なっているので、値だけ見ても
OCRが読んだのか、辞書が直したのか、規則が直したのかが分からない。

欄ごとに「経路」を積んでおき、出力と確認画面の両方で見せる。

    欄: (1) 診断名1
      1. 枠の切り出し   テンプレート seigo2_v1 の 1ページ目・左へ広げた
      2. 文字の認識     rapidocr:japan_v4   「心房細勣」
      3. 規則で訂正     カタカナ語の崩れ・誤字表（1,545語）
      4. 辞書で照合     傷病名（181語）  近さ 0.75
      5. ICDに寄せる    心房細動 I48

段の名前は固定にする（表示側で並べ替えたり色を付けたりするため）。
"""
from typing import Any, Dict, List, Optional

# 段の名前。**増やすときはブラウザ版（trace.js）と揃えること**
CROP = "枠の切り出し"
ENGINE = "文字の認識"
MARK = "印の判定"
RULE = "規則で訂正"
DICT = "辞書で照合"
ICD = "ICDに寄せる"
PLACE = "住所をそろえる"
UNIT = "単位をそろえる"
LABEL = "選択肢の言葉"
LLM = "LLMで校正"
DERIVE = "ほかの欄から補う"
HUMAN = "人が直した"

# 見せる順。読み取りの流れと同じにする
ORDER = [CROP, ENGINE, MARK, RULE, UNIT, DICT, ICD, PLACE, LABEL, LLM, DERIVE, HUMAN]


def add(entry: Dict[str, Any], step: str, detail: str = "",
        before: str = "", after: str = "") -> None:
    """1段ぶんの経路を足す。

    detail は「何を使ったか」。before/after は値が変わった段だけ入れる。
    """
    if entry is None:
        return
    rec: Dict[str, Any] = dict(step=step)
    if detail:
        rec["detail"] = detail
    if before or after:
        rec["before"], rec["after"] = before, after
    entry.setdefault("trace", []).append(rec)


def lines(entry: Dict[str, Any]) -> List[str]:
    """経路を、人が読める1行ずつにする。"""
    out = []
    for i, r in enumerate(entry.get("trace") or [], 1):
        text = f"{i}. {r['step']}"
        if r.get("detail"):
            text += f"　{r['detail']}"
        if r.get("before") or r.get("after"):
            text += f"　「{r.get('before', '')}」→「{r.get('after', '')}」"
        out.append(text)
    return out


def summary(entry: Dict[str, Any]) -> str:
    """どの仕組みを通ったかを、ひと続きで返す（表に入れる用）。"""
    seen: List[str] = []
    for r in entry.get("trace") or []:
        if r["step"] not in seen:
            seen.append(r["step"])
    return " → ".join(seen)


def engine_of(entry: Dict[str, Any]) -> Optional[str]:
    """文字を読んだ道具の名前。"""
    for r in entry.get("trace") or []:
        if r["step"] in (ENGINE, MARK):
            return r.get("detail")
    return entry.get("engine")
