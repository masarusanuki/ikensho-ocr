# -*- coding: utf-8 -*-
"""入力ファイル群から1件の主治医意見書レコードを組み立てる。"""
import os
import re
from dataclasses import dataclass, field as dc_field
from typing import Any, Dict, List, Optional

import numpy as np

from . import (align, anonymize, checkbox, dates as dates_mod, imaging,
               hospitals, labels as labels_mod, llm as llm_mod, ocr as ocr_mod,
               proofread, text_check, textbox)
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
    read_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return dict(
            template_id=self.template_id,
            ocr_engine=self.ocr_engine,
            anonymized=self.anonymized,
            pages=[vars(p) for p in self.pages],
            warnings=self.warnings,
            fields=self.fields,
        )


RE_SPACE = re.compile(r"\s")


def _add_note(entry: dict, msg: str) -> None:
    """確認画面に出す注記を足す。既にある注記は消さない。"""
    if not msg:
        return
    cur = entry.get("note")
    if cur and msg in cur:
        return
    entry["note"] = f"{cur}／{msg}" if cur else msg


def _mark_provisional(entry: dict, t: dict) -> None:
    """別様式から機械的に写した暫定位置の欄は、確信度を下げて注記を付ける。"""
    if not t.get("transferred"):
        return
    entry["confidence"] = round(entry.get("confidence", 0.0) * 0.5, 3)
    entry["note"] = "欄の位置が暫定です（管理画面のテンプレート編集で調整できます）"


def _read_date_slots(warped: np.ndarray, t: dict) -> dict:
    """日付欄を小枠ごとに読み、年・月・日を組み立てる。"""
    reader = ocr_mod.get_digit_reader()
    slots = t.get("slots") or {}
    read = reader.read_date(warped, t["rect"], slots)
    parts, confs, raw = {}, [], []
    for key in ("year", "month", "day"):
        value, conf = read.get(key, (None, 0.0))
        parts[key] = value
        if value is not None:
            confs.append(conf)
            raw.append(f"{key}={value}")
        else:
            rect = slots.get(key)
            empty = (not rect) or (not ocr_mod.has_ink(warped, rect, threshold=0.004))
            confs.append(0.85 if empty else 0.2)
    # 月・日の範囲を確かめる
    if parts.get("month") is not None and not 1 <= parts["month"] <= 12:
        parts["month"] = None
    if parts.get("day") is not None and not 1 <= parts["day"] <= 31:
        parts["day"] = None
    filled = [v for v in parts.values() if v is not None]
    conf = round(sum(confs) / len(confs), 3) if confs else 0.0
    if not filled:
        # 本当に空欄なのか、書いてあるのに読めなかったのかを区別する。
        # 読めなかった場合に「空欄・高確信」と出すと、確認画面の
        # 「要確認のみ表示」から漏れてしまう。
        has_any_ink = any(
            ocr_mod.has_ink(warped, r, threshold=0.004)
            for r in (slots.get(k) for k in ("year", "month", "day")) if r)
        if has_any_ink:
            return dict(value="", confidence=min(conf, 0.3), raw="", empty=False,
                        candidates=[], date=parts, slots_used=True,
                        note="日付を読み取れませんでした。数字を入力してください。")
        return dict(value="", confidence=0.9, raw="", empty=True, candidates=[],
                    date=parts, slots_used=True)
    return dict(value=dates_mod.format_wareki(parts), confidence=conf,
                raw=" ".join(raw), empty=False, candidates=[],
                date=parts, slots_used=True)


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


def _read_circle(warped: np.ndarray, rect: List[float], options: List[str],
                 always_pick: bool = False) -> dict:
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
    detail = [dict(opt=i, score=round(s, 4)) for i, s in enumerate(scores)]
    if ranked[0] <= 0.012:
        if not always_pick:
            return dict(value=None, confidence=0.2, detail=detail)
        # 必ず記入される欄なので、印が弱くても濃い方を採る（確信度は低くする）
        return dict(value=options[top], confidence=0.25, detail=detail, weak=True)
    conf = round(min(1.0, 0.30 + margin / 0.05 * 0.70), 3)
    return dict(value=options[top], confidence=conf, detail=detail)


def _apply_hospital_list(text_results: Dict[str, dict], assist) -> Optional[str]:
    """医療機関名を、厚生労働省の医療機関一覧と突き合わせる。

    意見書には施設名しか書かれないが、一覧の正式名称には開設者名が付く。
    所在地から都道府県を絞り、名前が十分に近ければ正式名称を採用し、
    所在地・電話が読めていなければ一覧の値で補う。

    決めきれない場合は候補を並べるだけにする。LLM に選ばせる場合も、
    **一覧にある名前**からしか選ばせない（無い病院を作り出さないため）。
    """
    entry = text_results.get("clinic_name")
    if not entry or entry.get("empty"):
        return None
    name = (entry.get("value") or "").strip()
    if len(name) < hospitals.MIN_QUERY or not hospitals.available():
        return None
    pref = hospitals.guess_pref(
        (text_results.get("clinic_address") or {}).get("value") or "",
        (text_results.get("applicant_address") or {}).get("value") or "")
    if not pref or pref not in hospitals.prefectures():
        return None
    hits = hospitals.find(name, pref, limit=5)
    if not hits:
        return None

    cands = entry.setdefault("candidates", [])
    for h in hits[:3]:
        cands.append(dict(value=h["name"], score=h["score"], source="hospital",
                          note=h.get("address") or ""))

    top = hits[0]
    if top["score"] < hospitals.ADOPT and assist is not None:
        # 一覧の候補からLLMに選ばせる。読み取り結果と重ならない答えは採らない。
        sug = assist.suggest("医療機関名", entry.get("raw") or name,
                             [h["name"] for h in hits])
        if sug:
            picked = next((h for h in hits
                           if h["name"] == sug.value), None)
            if picked and hospitals.match_score(name, picked["name"]) >= 0.60:
                top = picked
                entry["llm_candidate"] = picked["name"]
                _add_note(entry, "LLMが一覧から選びました。原本と見比べて確認してください。")
                top = dict(picked, score=max(picked["score"], hospitals.ADOPT))

    if top["score"] < hospitals.ADOPT:
        return None

    if top["name"] != entry.get("value"):
        entry["value"] = top["name"]
        _add_note(entry, f"医療機関一覧（{pref}）の名称に合わせました")
    entry["confidence"] = max(entry.get("confidence") or 0.0, 0.90)
    entry["hospital_code"] = top.get("code") or ""

    # 所在地・電話が読めていなければ一覧の値で補う
    for fid, key, label in (("clinic_address", "address", "所在地"),
                            ("clinic_phone", "phone", "電話")):
        ent = text_results.get(fid)
        value = top.get(key)
        if not ent or not value:
            continue
        cur = (ent.get("value") or "").strip()
        if cur and (ent.get("confidence") or 0) >= 0.5:
            continue
        ent["value"] = value
        ent["confidence"] = max(ent.get("confidence") or 0.0, 0.80)
        _add_note(ent, f"医療機関一覧の{label}で補いました（原本と違う場合は直してください）")
    return top["name"]


def _resolve_labels(box_values: Dict[str, dict], schema: Schema,
                    reads: Dict[str, str],
                    overrides: Dict[str, str]) -> Dict[str, dict]:
    """チェック欄ごとに、使う言葉（定義 / 管理画面で直したもの）を決める。"""
    out: Dict[str, dict] = {}
    for fid in box_values:
        f = schema.get(fid)
        if f is None or not f.options:
            continue
        for i, opt in enumerate(f.options):
            key = f"{fid}.{i}"
            out[key] = labels_mod.resolve(fid, i, opt, reads.get(key),
                                          overrides, f.options)
    return out


def extract_record(paths: List[str],
                   schema: Optional[Schema] = None,
                   templates: Optional[Dict[str, Template]] = None,
                   engine: str = "auto",
                   dictionaries: Optional[Dictionaries] = None,
                   dpi: int = imaging.DEFAULT_DPI,
                   keep_pages: bool = False,
                   anonymized: bool = False,
                   read_labels: bool = True,
                   use_llm: Optional[bool] = None,
                   llm_model: Optional[str] = None,
                   llm_budget: int = 8) -> Record:
    """複数の入力ファイルから1件のレコードを読み取る。

    PDF は複数ページ、画像・カメラ撮影は1ページずつ渡されることを想定し、
    どのページが様式の何ページ目かは自動判定する。

    read_labels を立てると、チェック欄の**後ろに書いてある言葉**も OCR で読む。
    様式を Word で作り直すと言葉が変わっていることがあるため。
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
    import datetime as _dt
    rec = Record(ocr_engine=ocr_engine.name,
                 read_at=_dt.datetime.now().astimezone().isoformat())
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
    label_reads: Dict[str, str] = {}
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
        page_readings = checkbox.read_boxes(warped, tp.boxes, blank)
        readings.extend(page_readings)
        if read_labels and ocr_engine.name != "none":
            # 印の付いた枠だけを読む。186枠すべてを読むと30秒ほどかかるうえ、
            # 出力に出るのは印の付いた枠の言葉だけのため。
            # 様式全体の言葉は管理画面から読み直せる。
            want = {(r.field, r.opt) for r in page_readings if r.checked}
            try:
                label_reads.update(
                    labels_mod.read_labels(warped, tp.boxes, ocr_engine, only=want))
            except Exception as exc:      # ラベルが読めなくても本体は続ける
                rec.warnings.append(f"チェック欄の言葉の読み取りに失敗しました（{exc}）")
        # 書き込みだけを残した差分。欄ごとに作り直すと重いので1ページ1回にする
        mark = text_check.mark_layer(warped, blank)

        for t, f in _text_fields_for_page(tp, schema):
            try:
                # 日付欄は「年」「月」「日」で区切った小枠ごとに数字だけを読む。
                # 各枠に1〜2桁の数字しか入らないので、そのまま読むより格段に正確になる。
                if f.is_date:
                    entry = _read_date_slots(warped, t)
                    _mark_provisional(entry, t)
                    text_results[f.id] = entry
                    continue
                if f.type == "circle":
                    entry = _read_circle(
                        warped, t["rect"], t.get("options") or f.options or [],
                        always_pick=bool(t.get("always_pick") or f.always_pick))
                    _mark_provisional(entry, t)
                    text_results[f.id] = entry
                    continue
                # 測った左端が記入の先頭に食い込んでいることがあるので、
                # 印刷内容にぶつからない範囲で左へ広げてから読む
                rect = textbox.widen_left(blank, t["rect"])
                if not ocr_mod.has_ink(warped, rect):
                    text_results[f.id] = dict(value="", confidence=0.95, raw="", empty=True,
                                              candidates=[])
                    continue
                # 白紙様式との差分で「書き込みが無い」と分かる欄は読まない。
                # 読ませると罫線やカッコから文字を作ってしまう（実測で拾い読みが出た）
                shape = text_check.written_shape(warped, blank, rect, mark)
                if shape is not None and shape["density"] < text_check.EMPTY_DENSITY:
                    text_results[f.id] = dict(
                        value="", confidence=0.90, raw="", empty=True, candidates=[],
                        note="この欄に書き込みが見当たりません（印刷の罫線だけです）")
                    continue
                # 罫線・カッコ・単位を含めたまま読むと精度が落ちるので、
                # 書き込みのある範囲に詰めてから認識に回す（検算には元の矩形を使う）
                roi = ocr_mod.prepare_roi(
                    warped, textbox.ink_crop(warped, blank, rect), pad=0.02)
                charset = t.get("charset") or getattr(f, "charset", "")
                multiline = f.type == "textarea"

                def _prepare(raw_text):
                    """辞書を引く前に、字体と誤字を直しておく。
                    こうしないと『褥創』が辞書の『褥瘡』に当たらない。
                    罫線やカッコ由来の記号は先に端から落とす。"""
                    trimmed, cut = text_check.trim_edges(raw_text or "")
                    pr = proofread.proofread_text(trimmed, multiline=multiline)
                    if cut:
                        pr.corrections.extend(
                            proofread.Correction(before="", after="", reason=c) for c in cut)
                    return pr
                if isinstance(ocr_engine, ocr_mod.EnsembleOcr):
                    # 複数エンジンの結果を辞書照合まで通し、最も確からしいものを採る
                    best = None
                    for res in ocr_engine.read_all(roi, multiline, charset):
                        pr = _prepare(res.text)
                        cv, cc, cands = dicts.correct(f, pr.text, res.confidence)
                        if best is None or cc > best[1]:
                            best = (cv, cc, cands, res.text, res.engine, pr)
                    corrected, conf, cands, raw_text, used, pr = best
                    entry = dict(value=corrected, confidence=round(conf, 3),
                                 raw=raw_text, candidates=cands, empty=False,
                                 engine=used)
                else:
                    res = ocr_engine.read(roi, multiline=multiline, charset=charset)
                    pr = _prepare(res.text)
                    corrected, conf, cands = dicts.correct(f, pr.text, res.confidence)
                    entry = dict(value=corrected, confidence=round(conf, 3),
                                 raw=res.text, candidates=cands, empty=False,
                                 engine=res.engine)
                # 身長・体重は小数1桁。小さな小数点は読み落とされやすいので、
                # 範囲から外れていて小数点を入れると収まる場合だけ戻す
                if entry.get("value"):
                    fixed, note = proofread.fix_decimal_point(f.id, entry["value"])
                    if note is not None:
                        entry["value"] = fixed
                        entry.setdefault("corrections", []).append(
                            dict(before=note.before, after=note.after, reason=note.reason))
                # ふりがな欄はひらがなに揃える（様式が「ふりがな」のため）
                if f.charset == "kana" and entry.get("value"):
                    fixed, note = proofread.to_furigana(entry["value"])
                    if note is not None:
                        entry["value"] = fixed
                        entry.setdefault("corrections", []).append(
                            dict(before=note.before, after=note.after, reason=note.reason))

                # 書かれている量・端の接し方と、読めた文字列を突き合わせる
                chk = text_check.check(entry.get("value") or "", warped, blank, rect,
                                       charset, mark)
                if chk["notes"]:
                    entry["confidence"] = round(entry["confidence"] * chk["penalty"], 3)
                    for n in chk["notes"]:
                        _add_note(entry, n)
                entry["expected_chars"] = chk["expected"]

                # 記述の欄に1文字だけというのは、まず記入ではなく
                # 罫線やゴミを拾ったもの。空にして要確認にする。
                # 元の読みは raw に残るので、確認画面の「OCR生読み」で戻せる。
                if (f.type in ("text", "textarea") and not charset
                        and not f.options
                        and len(RE_SPACE.sub("", entry.get("value") or "")) == 1):
                    entry["value"] = ""
                    entry["confidence"] = min(entry.get("confidence") or 0.0, 0.30)
                    _add_note(entry,
                              "1文字だけ読めましたが、記述としてあり得ないため空にしました"
                              "（必要なら「OCR生読み」から戻せます）")

                # 日本語チェックの結果を記録する（訂正は辞書照合の前に済ませている）
                if pr.corrections:
                    # 既にある訂正（ふりがなの変換など）を消さないこと
                    entry.setdefault("corrections", []).extend(
                        dict(before=c.before, after=c.after, reason=c.reason)
                        for c in pr.corrections)
                entry["japanese_score"] = pr.japanese_score
                if pr.japanese_score < 0.6:
                    entry["confidence"] = round(entry["confidence"] * 0.6, 3)
                    _add_note(entry, pr.note)

                # 自由記述はLLMに校正させ、結果は候補として並べる（自動採用はしない）
                if assist and llm_left > 0 and multiline and len(entry["value"]) >= 20:
                    llm_left -= 1
                    lp = proofread.proofread_with_llm(assist, entry["value"], f.label)
                    if lp:
                        entry.setdefault("candidates", []).insert(
                            0, dict(value=entry["value"], score=None, source="raw",
                                    note="LLM補正前の読み取り"))
                        entry["value"] = lp.text
                        entry["llm_applied"] = True
                        _add_note(entry, lp.note)

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
                        # LLM の結果を採用する。出力は辞書に載っている語に限っているので
                        # 書かれていない病名を作り出すことはない。
                        # 元の読み取りは raw に残し、画面には「LLMが補正」と出す。
                        entry["value"] = sug.value
                        entry["llm_applied"] = True
                        entry["confidence"] = max(entry.get("confidence", 0.0), 0.55)
                        _add_note(entry, "LLMが補正しました。原文と見比べて確認してください。")
                if t.get("transferred"):
                    # 別様式から機械的に写した暫定位置。枠がずれている可能性がある
                    entry["confidence"] = round(entry["confidence"] * 0.5, 3)
                    _add_note(entry, "欄の位置が暫定です（管理画面のテンプレート編集で調整できます）")
                text_results[f.id] = entry

            except Exception as exc:
                # 1欄の失敗で1件まるごと落とさない。読めなかった欄だけ要確認にする
                rec.warnings.append(f"{f.label}: 欄の読み取りに失敗しました（{exc}）")
                text_results[f.id] = dict(
                    value="", confidence=0.0, raw="", empty=False, candidates=[],
                    note=f"この欄の読み取りに失敗しました（{exc}）")
    # 医療機関名は一覧（厚生労働省）と突き合わせる。所在地・電話も補える。
    try:
        _apply_hospital_list(text_results, assist)
    except Exception as exc:               # 一覧が壊れていても読み取りは続ける
        rec.warnings.append(f"医療機関一覧との照合に失敗しました（{exc}）")

    expected_pages = ([p.index for p in templates[rec.template_id].pages]
                      if rec.template_id in templates else [1, 2])
    missing = [i for i in expected_pages if i not in warped_pages]
    if missing:
        rec.warnings.append(
            "未取得のページ: " + "、".join(f"{i}ページ目" for i in missing))

    box_values = checkbox.resolve_groups(readings, schema)
    label_overrides = labels_mod.load_overrides(rec.template_id or "")
    label_info = _resolve_labels(box_values, schema, label_reads, label_overrides)
    if any(v.get("changed") for v in label_info.values()):
        rec.warnings.append(
            "チェック欄の言葉が定義と違って読めた箇所があります"
            "（管理画面の「チェック欄の言葉」で直せます）")

    # 日付欄は年・月・日に分けておく。確認画面で数字だけ直せるようにするため。
    for f in schema:
        if not f.is_date or f.id not in text_results:
            continue
        entry = text_results[f.id]
        era = f.default_era
        fixed = bool(f.default_era)          # 様式に印刷されている元号は動かさない
        if f.era_field:
            picked = text_results.get(f.era_field, {}).get("value")
            era = picked or era
            fixed = False
        if entry.get("slots_used"):
            parts = dict(entry.get("date") or {})
            parts["era"] = dates_mod.canonical_era(era)
            info = dict(parts={k: parts.get(k) for k in ("year", "month", "day")},
                        era=parts["era"],
                        text=dates_mod.format_wareki(parts),
                        gregorian=dates_mod.to_gregorian(parts["era"], parts.get("year"),
                                                         parts.get("month"), parts.get("day")))
        else:
            info = dates_mod.enrich(entry.get("value") or "", era, fixed_era=fixed)
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
            words = [label_info.get(f"{f.id}.{i}", {}).get("word", o)
                     for i, o in enumerate(f.options)]
            if words != list(f.options):
                entry["option_words"] = words
                labels_mod.apply_words(entry, list(f.options), words)
            marks = [label_info[f"{f.id}.{i}"] for i in range(len(f.options))
                     if f"{f.id}.{i}" in label_info]
            if any(m.get("changed") or m.get("source") == "修正" for m in marks):
                entry["label_notes"] = marks
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
