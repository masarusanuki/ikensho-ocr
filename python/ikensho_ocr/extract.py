# -*- coding: utf-8 -*-
"""入力ファイル群から1件の主治医意見書レコードを組み立てる。"""
import os
from dataclasses import dataclass, field as dc_field
from typing import Any, Dict, List, Optional

import numpy as np

from . import (align, anonymize, checkbox, dates as dates_mod, imaging,
               llm as llm_mod, ocr as ocr_mod, proofread)
from .dictionaries import Dictionaries, DEFAULT_DICTIONARIES
from .schema import Schema, load_schema
from .templates import Template, load_templates

# 確信度の区分（確認画面の色分けに使う）
CONF_HIGH = 0.80
CONF_MID = 0.50


def confidence_level(conf: float) -> str:
    if conf >= CONF_HIGH:
        return "high"
    if conf >= CONF_MID:
        return "medium"
    return "low"


@dataclass
class PageInfo:
    source: str
    source_page: int
    template_id: Optional[str]
    page_index: Optional[int]
    score: float
    inliers: int
    dewarped: bool
    matched: bool


@dataclass
class Record:
    fields: Dict[str, dict] = dc_field(default_factory=dict)
    pages: List[PageInfo] = dc_field(default_factory=list)
    template_id: Optional[str] = None
    warnings: List[str] = dc_field(default_factory=list)
    ocr_engine: str = "none"
    anonymized: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return dict(
            template_id=self.template_id,
            ocr_engine=self.ocr_engine,
            anonymized=self.anonymized,
            pages=[vars(p) for p in self.pages],
            warnings=self.warnings,
            fields=self.fields,
        )


def _llm_worth_asking(entry) -> bool:
    """LLM に聞く価値がある欄か。

    辞書で十分に決まった欄や、そもそも読めていない欄に聞いても意味が無く、
    処理時間が延びるだけなので絞り込む。
    """
    if not entry.get("raw") or entry.get("empty"):
        return False
    cands = [c for c in (entry.get("candidates") or []) if c.get("source") != "llm"]
    if not cands:
        return False                       # 選ばせる候補が無い（創作させない）
    top = cands[0].get("score")
    if top is not None and top >= 0.72:
        return False                       # 辞書で決着済み
    if entry.get("japanese_score", 1.0) < 0.5:
        return False                       # 読み取り自体が失敗している
    return entry.get("confidence", 0.0) < 0.72


def _text_fields_for_page(tpl_page, schema: Schema):
    for t in tpl_page.texts:
        f = schema.get(t["field"])
        if f is not None:
            yield t, f


def _read_circle(warped: np.ndarray, rect: List[float], options: List[str]) -> dict:
    """「男・女」「明・大・昭」など、印刷済みの選択肢を丸で囲む方式を読む。

    欄を選択肢数に等分し、丸印（＝周囲より濃い領域）が最も強い区画を選ぶ。
    """
    import cv2
    H, W = warped.shape
    x, y, w, h = rect
    x0, y0 = max(0, int(x * W)), max(0, int(y * H))
    x1, y1 = min(W, int((x + w) * W)), min(H, int((y + h) * H))
    if x1 - x0 < 6 or y1 - y0 < 6 or not options:
        return dict(value=None, confidence=0.0, detail=[])
    roi = warped[y0:y1, x0:x1]
    bw = cv2.adaptiveThreshold(roi, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                               cv2.THRESH_BINARY_INV, 31, 12) > 0
    n = len(options)
    vertical = (y1 - y0) > (x1 - x0) * 1.4      # 「男・女」は縦並び
    scores = []
    for i in range(n):
        if vertical:
            a, b = int(bw.shape[0] * i / n), int(bw.shape[0] * (i + 1) / n)
            seg = bw[a:b, :]
        else:
            a, b = int(bw.shape[1] * i / n), int(bw.shape[1] * (i + 1) / n)
            seg = bw[:, a:b]
        scores.append(float(seg.mean()) if seg.size else 0.0)
    base = float(np.median(scores))
    excess = [s - base for s in scores]
    top = int(np.argmax(excess))
    ranked = sorted(excess, reverse=True)
    margin = ranked[0] - (ranked[1] if len(ranked) > 1 else 0.0)
    if ranked[0] <= 0.012:
        return dict(value=None, confidence=0.2,
                    detail=[dict(opt=i, score=round(s, 4)) for i, s in enumerate(scores)])
    conf = round(min(1.0, 0.30 + margin / 0.05 * 0.70), 3)
    return dict(value=options[top], confidence=conf,
                detail=[dict(opt=i, score=round(s, 4)) for i, s in enumerate(scores)])


def extract_record(paths: List[str],
                   schema: Optional[Schema] = None,
                   templates: Optional[Dict[str, Template]] = None,
                   engine: str = "auto",
                   dictionaries: Optional[Dictionaries] = None,
                   dpi: int = imaging.DEFAULT_DPI,
                   keep_pages: bool = False,
                   anonymized: bool = False,
                   use_llm: Optional[bool] = None,
                   llm_model: Optional[str] = None,
                   llm_budget: int = 8) -> Record:
    """複数の入力ファイルから1件のレコードを読み取る。

    PDF は複数ページ、画像・カメラ撮影は1ページずつ渡されることを想定し、
    どのページが様式の何ページ目かは自動判定する。
    """
    schema = schema or load_schema()
    templates = templates or load_templates()
    dicts = dictionaries if dictionaries is not None else DEFAULT_DICTIONARIES()
    ocr_engine = ocr_mod.get_engine(engine)
    # LLM は「候補を出すだけ」。値の自動確定には使わない（llm.py の説明を参照）
    # 既定は「使える環境なら使う」。処理時間を抑えるため呼び出す欄は絞る。
    want_llm = llm_mod.available() if use_llm is None else bool(use_llm)
    assist = llm_mod.get_assist(want_llm, llm_model)
    llm_left = llm_budget

    src_pages: List[imaging.SourcePage] = []
    rec = Record(ocr_engine=ocr_engine.name)
    if use_llm and assist is None:
        rec.warnings.append(
            "LLM候補は使えません（llama-cpp-python とGGUFモデルを用意してください）")
    for p in paths:
        try:
            src_pages.extend(imaging.load_any(p, dpi))
        except Exception as exc:
            rec.warnings.append(f"{os.path.basename(p)}: 読み込み失敗 ({exc})")

    if not src_pages:
        rec.warnings.append("読み取れるページがありません")
        return rec

    matches = align.assign_pages([align.match_page(sp.image, templates) for sp in src_pages])

    seen_pages: Dict[int, float] = {}
    readings: List[checkbox.BoxReading] = []
    text_results: Dict[str, dict] = {}
    warped_pages: Dict[int, np.ndarray] = {}

    for sp, m in zip(src_pages, matches):
        info = PageInfo(source=sp.source, source_page=sp.source_page,
                        template_id=m.template_id if m else None,
                        page_index=m.page_index if m else None,
                        score=m.score if m else 0.0,
                        inliers=m.inliers if m else 0,
                        dewarped=sp.dewarped, matched=m is not None)
        rec.pages.append(info)
        if m is None:
            rec.warnings.append(
                f"{sp.source} p{sp.source_page}: 様式を判別できませんでした")
            continue
        rec.template_id = m.template_id
        # 同じページが複数入っている場合はスコアの高い方を採用する
        if m.page_index in seen_pages and seen_pages[m.page_index] >= m.score:
            rec.warnings.append(
                f"{sp.source} p{sp.source_page}: {m.page_index}ページ目が重複しているため無視しました")
            continue
        seen_pages[m.page_index] = m.score
        warped_pages[m.page_index] = m.warped

    for page_index, warped in sorted(warped_pages.items()):
        tpl = templates[rec.template_id]
        tp = tpl.page(page_index)
        if tp is None:
            continue
        blank = tp.blank_image(tpl.base_dir)
        readings.extend(checkbox.read_boxes(warped, tp.boxes, blank))

        for t, f in _text_fields_for_page(tp, schema):
            if f.type == "circle":
                text_results[f.id] = _read_circle(warped, t["rect"], t.get("options") or f.options or [])
                continue
            if not ocr_mod.has_ink(warped, t["rect"]):
                text_results[f.id] = dict(value="", confidence=0.95, raw="", empty=True,
                                          candidates=[])
                continue
            roi = ocr_mod.prepare_roi(warped, t["rect"], pad=0.02)
            charset = t.get("charset") or getattr(f, "charset", "")
            multiline = f.type == "textarea"
            if isinstance(ocr_engine, ocr_mod.EnsembleOcr):
                # 複数エンジンの結果を辞書照合まで通し、最も確からしいものを採る
                best = None
                for res in ocr_engine.read_all(roi, multiline, charset):
                    cv, cc, cands = dicts.correct(f, res.text, res.confidence)
                    if best is None or cc > best[1]:
                        best = (cv, cc, cands, res.text, res.engine)
                corrected, conf, cands, raw_text, used = best
                entry = dict(value=corrected, confidence=round(conf, 3),
                             raw=raw_text, candidates=cands, empty=False,
                             engine=used)
            else:
                res = ocr_engine.read(roi, multiline=multiline, charset=charset)
                corrected, conf, cands = dicts.correct(f, res.text, res.confidence)
                entry = dict(value=corrected, confidence=round(conf, 3),
                             raw=res.text, candidates=cands, empty=False,
                             engine=res.engine)
            # 日本語として妥当か調べ、誤字を直す（規則ベース・常時）
            pr = proofread.proofread_text(entry["value"], multiline=multiline)
            if pr.corrections:
                entry["value"] = pr.text
                entry["corrections"] = [dict(before=c.before, after=c.after,
                                             reason=c.reason) for c in pr.corrections]
            entry["japanese_score"] = pr.japanese_score
            if pr.japanese_score < 0.6:
                entry["confidence"] = round(entry["confidence"] * 0.6, 3)
                entry["note"] = pr.note

            # 自由記述はLLMに校正させ、結果は候補として並べる（自動採用はしない）
            if assist and llm_left > 0 and multiline and len(entry["value"]) >= 20:
                llm_left -= 1
                lp = proofread.proofread_with_llm(assist, entry["value"], f.label)
                if lp:
                    entry.setdefault("candidates", []).insert(
                        0, dict(value=lp.text, score=None, source="llm", note=lp.note))

            # 辞書で決めきれなかった欄だけ、小型LLMに候補を選ばせる（自動採用はしない）
            if assist and llm_left > 0 and _llm_worth_asking(entry):
                llm_left -= 1
                names = [c["value"] for c in (entry.get("candidates") or [])
                         if c.get("source") != "llm"][:5]
                sug = assist.suggest(f.label, entry["raw"], names)
                if sug and sug.value != entry["value"]:
                    entry.setdefault("candidates", []).insert(
                        0, dict(value=sug.value, score=None, source="llm",
                                note=sug.note))
                    entry["llm_candidate"] = sug.value
            if t.get("transferred"):
                # 別様式から機械的に写した暫定位置。枠がずれている可能性がある
                entry["confidence"] = round(entry["confidence"] * 0.5, 3)
                entry["note"] = "欄の位置が暫定です（管理画面のテンプレート編集で調整できます）"
            text_results[f.id] = entry

    missing = [i for i in (1, 2) if i not in warped_pages]
    if missing:
        rec.warnings.append(
            "未取得のページ: " + "、".join(f"{i}ページ目" for i in missing))

    box_values = checkbox.resolve_groups(readings, schema)

    # 日付欄は年・月・日に分けておく。確認画面で数字だけ直せるようにするため。
    for f in schema:
        if not f.is_date or f.id not in text_results:
            continue
        entry = text_results[f.id]
        era = f.default_era
        if f.era_field:
            picked = text_results.get(f.era_field, {}).get("value")
            era = picked or era
        info = dates_mod.enrich(entry.get("value") or "", era)
        entry["date"] = info["parts"]
        entry["era"] = info["era"]
        entry["gregorian"] = info["gregorian"]
        if info["text"]:
            entry["value"] = info["text"]

    for f in schema:
        entry: Dict[str, Any]
        if f.id in box_values:
            entry = dict(box_values[f.id])
        elif f.id in text_results:
            entry = dict(text_results[f.id])
        else:
            entry = dict(value=None, confidence=0.0)
        entry.setdefault("value", None)
        entry.setdefault("confidence", 0.0)
        entry["level"] = confidence_level(entry["confidence"])
        entry["label"] = f.label
        entry["type"] = f.type
        entry["section"] = f.section_title
        entry["page"] = f.page
        if f.options:
            entry["options"] = f.options
        rec.fields[f.id] = entry

    # 匿名化加工済みデータの扱い（氏名欄が白抜きなら「匿名化済み」）
    # OCR を使っていない場合はテキスト欄が全て空になるので、自動判定はしない
    can_detect = ocr_engine.name != "none"
    if anonymized or (can_detect and anonymize.looks_anonymized(rec.fields, schema)):
        anonymize.apply(rec.fields, schema, force=anonymized)
        rec.anonymized = True   # type: ignore[attr-defined]
        if anonymized:
            rec.warnings.append("匿名化加工済みデータとして処理しました（住所・連絡先はマスク済み）")

    if keep_pages:
        rec.warped_pages = warped_pages    # type: ignore[attr-defined]
    return rec
