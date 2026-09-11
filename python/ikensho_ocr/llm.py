# -*- coding: utf-8 -*-
"""小型LLMによる読み取り候補の提示（任意機能・CPUで動作）。

**この機能は候補を出すだけで、値を自動で確定しません。**

理由: 小型LLMは、意味をなさないOCR結果からでも、もっともらしい病名を
自信ありげに作り出す。実測で「回提 6四6」という読み取り不能な文字列から
「脳梗塞」を出力した。診療情報でこれを自動採用するのは危険なため、
  1. 出力は辞書に載っている語だけに限る（創作を許さない）
  2. OCR結果と文字が十分に重なっているものだけを採用する
  3. 確信度は上げない。確認画面に「LLM候補」として並べるだけ
という三重の制限をかけている。

まずは辞書照合（編集距離ベース）で足りる場合が多い。LLM はその補助に使う。
"""
import os
import re
import threading
from dataclasses import dataclass
from typing import List, Optional

from .dictionaries import normalize, similarity

# 既定のモデル探索先
DEFAULT_MODEL_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "models")

SYSTEM_PROMPT = (
    "あなたは日本語の医療文書のOCR結果を校正する補助です。"
    "与えられたOCR結果と候補一覧から、最も確からしい正式名称を1つだけ出力します。"
    "候補一覧にない語を出力してはいけません。"
    "判断できない場合は 不明 とだけ出力します。"
    "説明や記号は付けず、語だけを出力します。"
)

# OCR結果と候補がこれだけ文字を共有していなければ、無関係な創作とみなす
MIN_CHAR_OVERLAP = 0.34
# 手がかりが短すぎる場合は聞かない。実測で「一」の1文字から
# 「一過性脳虚血発作」を出力した例があるため。
MIN_OCR_LENGTH = 3


# 万一「思考」を出すモデルが指定された場合に備えて取り除く
THINK_RE = re.compile(r"<think>.*?</think>", re.S)
# 思考モードを持たないモデルを優先し、その中では軽いものを先に選ぶ。
# この機能は「候補を出すだけ」なので、精度より処理時間を優先する。
# より正確な大きいモデルを使いたい場合は --llm-model で明示する。
PREFERRED = ("qwen2.5-1.5b", "qwen2.5-3b", "qwen3-1.7b", "instruct-2507", "instruct")


def strip_thinking(text: str) -> str:
    text = THINK_RE.sub("", text or "")
    return text.replace("<think>", "").replace("</think>", "").strip()


@dataclass
class Suggestion:
    value: str
    source: str = "llm"
    note: str = ""


def _char_overlap(a: str, b: str) -> float:
    na, nb = set(normalize(a)), set(normalize(b))
    if not na or not nb:
        return 0.0
    return len(na & nb) / min(len(na), len(nb))


class LlmAssist:
    """llama.cpp 経由の小型LLM。導入されていなければ何もしない。

    **実体は1つを使い回すので、同時に呼んではいけない。**
    llama.cpp の文脈は同時呼び出しに耐えず、踏むと `GGML_ASSERT` で
    **プロセスごと落ちる**（サーバなら処理中の全部が巻き添えになる）。
    入り口に錠をかけて、必ず順番に通す。
    """

    def __init__(self, model_path: Optional[str] = None, n_ctx: int = 1024,
                 max_tokens: int = 24, threads: Optional[int] = None):
        self.available = False
        self._lock = threading.Lock()
        self.model_path = model_path or self._find_model()
        self.max_tokens = max_tokens
        self._llm = None
        if not self.model_path or not os.path.exists(self.model_path):
            return
        try:
            from llama_cpp import Llama
        except Exception:
            return
        try:
            self._llm = Llama(model_path=self.model_path, n_ctx=n_ctx,
                              n_threads=threads or (os.cpu_count() or 4),
                              verbose=False)
            self.available = True
        except Exception:
            self._llm = None

    @staticmethod
    def _find_model() -> Optional[str]:
        env = os.environ.get("IKENSHO_LLM_MODEL")
        if env:
            return env
        if not os.path.isdir(DEFAULT_MODEL_DIR):
            return None
        names = [n for n in sorted(os.listdir(DEFAULT_MODEL_DIR))
                 if n.lower().endswith(".gguf")]
        if not names:
            return None
        # 思考モードを持たない Instruct 系を優先する
        for key in PREFERRED:
            for n in names:
                if key in n.lower():
                    return os.path.join(DEFAULT_MODEL_DIR, n)
        return os.path.join(DEFAULT_MODEL_DIR, names[0])

    def suggest(self, field_label: str, ocr_text: str,
                candidates: List[str]) -> Optional[Suggestion]:
        """候補一覧から最も確からしいものを選ばせる。

        候補が無い場合は何もしない（自由生成はさせない）。
        """
        if not self.available or not candidates:
            return None
        if len(normalize(ocr_text)) < MIN_OCR_LENGTH:
            return None                    # 手がかりが短すぎる
        prompt = (f"項目: {field_label}\n"
                  f"OCR結果: {ocr_text[:60]}\n"
                  f"候補: {' / '.join(candidates[:5])}\n"
                  f"正式名称:")
        try:
            with self._lock:           # 同時に呼ぶと落ちる（クラスの説明を参照）
                res = self._llm.create_chat_completion(
                    messages=[{"role": "system", "content": SYSTEM_PROMPT},
                              {"role": "user", "content": prompt}],
                    max_tokens=self.max_tokens, temperature=0.0)
            out = strip_thinking(res["choices"][0]["message"]["content"])
            out = out.split("\n")[0].strip()
        except Exception:
            return None
        if not out or out == "不明":
            return None

        # 1) 候補一覧に無い語は捨てる（創作の防止）
        match = None
        for c in candidates:
            if normalize(c) == normalize(out) or similarity(c, out) >= 0.9:
                match = c
                break
        if match is None:
            return None
        # 2) OCR結果と文字が重ならないものは捨てる（無関係な語の防止）
        if _char_overlap(ocr_text, match) < MIN_CHAR_OVERLAP:
            return None
        return Suggestion(value=match, source="llm",
                          note="LLMによる候補です。内容を確認してから採用してください。")


    def complete(self, system: str, prompt: str, max_tokens: int = 256) -> str:
        """自由な補完。文章の校正に使う。"""
        if not self.available:
            return ""
        try:
            with self._lock:           # 同時に呼ぶと落ちる（クラスの説明を参照）
                res = self._llm.create_chat_completion(
                    messages=[{"role": "system", "content": system},
                              {"role": "user", "content": prompt}],
                    max_tokens=max_tokens, temperature=0.0)
            return strip_thinking(res["choices"][0]["message"]["content"])
        except Exception:
            return ""


_CACHE: Optional[LlmAssist] = None


def available() -> bool:
    """LLM候補提示を使える環境か（実行環境とモデルがそろっているか）。"""
    try:
        import llama_cpp  # noqa: F401
    except Exception:
        return False
    path = LlmAssist._find_model()
    return bool(path and os.path.exists(path))


def get_assist(enabled: bool = False, model_path: Optional[str] = None
               ) -> Optional[LlmAssist]:
    global _CACHE
    if not enabled:
        return None
    if _CACHE is None:
        _CACHE = LlmAssist(model_path)
    return _CACHE if _CACHE.available else None
