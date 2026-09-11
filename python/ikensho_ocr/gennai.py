# -*- coding: utf-8 -*-
"""源内（デジタル庁の生成AI利活用基盤）の「行政実務用AIアプリ」として応答する。

源内 Web は外部の REST API を「AI アプリ」として登録し、呼び出せる。
その取り決めに合わせた入り口をここに置く。

    受け取り  {"inputs": {..., "files": [...base64...]}}
    返し      {"outputs": "Markdown のテキスト"}

**既定では開かない。** `ikensho serve --gennai` と明示したときだけ開く。
主治医意見書は要配慮個人情報であり、源内はクラウド上のサービスなので、
「すべて端末内で処理する」というこのアプリの原則から外れるため。
開くかどうかは運用側の判断に委ねる。

仕様の出どころ:
  https://github.com/digital-go-jp/genai-web/blob/main/docs/AIアプリAPI仕様.md
仕様書に「2026年3月時点のものであり試行錯誤中。今後大きく変わる可能性が
あります」と明記されているため、**受け取り側はゆるく**（表記ゆれを吸収して）作る。
"""
import base64
import binascii
from typing import Any, Dict, List, Optional, Tuple

# 源内の「リクエスト形式」に貼り付ける JSON。
# この定義から、源内 Web が入力画面を組み立てる。
REQUEST_FORM: Dict[str, Any] = {
    "files": {
        "type": "file",
        "title": "主治医意見書のPDFまたは画像",
        "desc": "1通ぶん（2ページ）をまとめて選んでください。"
                "写真の場合は1ページずつでも構いません。",
        "required": True,
        "accept": "application/pdf,image/png,image/jpeg",
        "multiple": True,
        "max_size": "20MB",
        "max_file_count": 8,
    },
    "format": {
        "type": "select",
        "title": "出力の形",
        "desc": "「読みやすい形」は様式の並びどおりに整えたものです。",
        "required": False,
        "default_value": "markdown",
        "options": [
            {"label": "読みやすい形（様式の並び）", "value": "markdown"},
            {"label": "JSON（様式の並び）", "value": "json"},
        ],
    },
    "anonymized": {
        "type": "checkbox",
        "title": "匿名化加工済みデータとして扱う",
        "desc": "氏名が白抜きの研究用データの場合に選んでください。",
        "required": False,
        "options": [{"label": "匿名化加工済み", "value": "yes"}],
    },
}

MAX_FILES = 8
MAX_BYTES = 20 * 1024 * 1024      # 1ファイルあたり


class GennaiError(Exception):
    """源内からの受け取りが取り決めに合わない。"""


def _one_file(item: Any) -> List[Tuple[str, str]]:
    """ファイル1件ぶんを (ファイル名, base64) の並びにする。

    仕様書の中で書き方が2通りあるため、どちらも受ける。
      同期の例  {"key": ..., "files": [{"filename": ..., "content": ...}]}
      非同期の例 {"key": ..., "filename": ..., "contents": ...}
    """
    if not isinstance(item, dict):
        return []
    inner = item.get("files")
    if isinstance(inner, list):
        out = []
        for f in inner:
            if not isinstance(f, dict):
                continue
            data = f.get("content") or f.get("contents")
            if data:
                out.append((str(f.get("filename") or "input"), str(data)))
        return out
    data = item.get("content") or item.get("contents")
    if data:
        return [(str(item.get("filename") or "input"), str(data))]
    return []


def parse_files(inputs: Dict[str, Any]) -> List[Tuple[str, bytes]]:
    """`inputs.files` を (ファイル名, 中身) の並びにして返す。"""
    raw = inputs.get("files")
    if raw is None:
        raise GennaiError("ファイルがありません（inputs.files）")
    items = raw if isinstance(raw, list) else [raw]
    pairs: List[Tuple[str, str]] = []
    for item in items:
        pairs.extend(_one_file(item))
    if not pairs:
        raise GennaiError("ファイルがありません（inputs.files）")
    if len(pairs) > MAX_FILES:
        raise GennaiError(f"ファイルが多すぎます（{len(pairs)} 件。上限 {MAX_FILES} 件）")
    out: List[Tuple[str, bytes]] = []
    for name, data in pairs:
        # データURL形式（data:application/pdf;base64,....）で来ても受ける
        if "," in data[:64] and data[:5].lower() == "data:":
            data = data.split(",", 1)[1]
        try:
            blob = base64.b64decode(data, validate=False)
        except (binascii.Error, ValueError) as exc:
            raise GennaiError(f"{name}: base64 を読めません（{exc}）") from exc
        if not blob:
            raise GennaiError(f"{name}: 中身が空です")
        if len(blob) > MAX_BYTES:
            raise GennaiError(f"{name}: 大きすぎます"
                              f"（{len(blob) / 1048576:.1f}MB。上限 {MAX_BYTES // 1048576}MB）")
        out.append((_with_extension(_safe_name(name), blob), blob))
    return out


# 中身から種類を見分ける（拡張子が無い・当てにならない場合の備え）。
# `imaging.load_any` は拡張子で処理を振り分けるため、拡張子が無いと読めない。
_MAGIC = (
    (b"%PDF", ".pdf"),
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"\xff\xd8\xff", ".jpg"),
    (b"II*\x00", ".tif"),
    (b"MM\x00*", ".tif"),
)


def _safe_name(name: str) -> str:
    """保存に使えるファイル名にする（区切り文字と上位参照を落とす）。"""
    base = str(name).replace("\\", "/").split("/")[-1]
    base = base.replace("..", "_").strip()
    return base or "input"


def _with_extension(name: str, blob: bytes) -> str:
    """拡張子が無い・知らない場合は、中身を見て付ける。

    読み込み側は拡張子で処理を振り分けるので、無いとそのまま落ちる。
    """
    known = (".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp")
    if name.lower().endswith(known):
        return name
    for magic, ext in _MAGIC:
        if blob.startswith(magic):
            return name + ext
    return name


def _truthy(value: Any) -> bool:
    """チェックボックスの値。源内は文字列でもカンマ区切りでも送ってくる。"""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() not in ("", "false", "0", "no", "off")


def options(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """ファイル以外の入力を読む。"""
    fmt = str(inputs.get("format") or "markdown").strip().lower()
    if fmt not in ("markdown", "json"):
        fmt = "markdown"
    return dict(format=fmt, anonymized=_truthy(inputs.get("anonymized")))


# ------------------------------------------------------------ 読みやすい形

def _value_text(item: Dict[str, Any]) -> str:
    """1項目の値を、そのまま読める文字列にする。"""
    marks = item.get("チェック")
    if marks:
        picked = [m["言葉"] for m in marks if m.get("印")]
        struck = [m["言葉"] for m in marks if m.get("二重線で訂正")]
        text = "、".join(picked) if picked else "（印なし）"
        if struck:
            text += f"　※二重線で消された印: {'、'.join(struck)}"
        return text
    value = item.get("値")
    if value is None or value == "":
        return "（空欄）"
    if isinstance(value, list):
        return "、".join(str(v) for v in value) if value else "（空欄）"
    if isinstance(value, bool):
        return "該当" if value else "該当なし"
    return str(value)


def _item_lines(item: Dict[str, Any], indent: str = "") -> List[str]:
    """1項目を Markdown の行にする。"""
    note = []
    if item.get("確信度の段階") in ("低", "中"):
        note.append(f"要確認（確信度 {item.get('確信度の段階')}）")
    if item.get("人が直した"):
        note.append("人が直した")
    if item.get("ICD10"):
        icd = item["ICD10"]
        if item.get("ICDの分類名"):
            icd += f"／{item['ICDの分類名']}"
        note.append(f"ICD {icd}")
    if item.get("特定疾病"):
        note.append("特定疾病")
    if item.get("西暦"):
        note.append(f"西暦 {item['西暦']}")
    tail = f"　<sub>{' ・ '.join(note)}</sub>" if note else ""
    return [f"{indent}- **{item.get('項目', '')}**: {_value_text(item)}{tail}"]


def to_markdown(form: Dict[str, Any]) -> str:
    """様式の並びそのままの JSON を、源内の画面で読める Markdown にする。

    源内 Web は `outputs` のテキストを Markdown として表示する。
    """
    lines: List[str] = [f"# {form.get('様式', '主治医意見書')} の読み取り結果", ""]
    src = form.get("元ファイル") or []
    if src:
        names = "、".join(dict.fromkeys(str(p.get("ファイル")) for p in src))
        lines.append(f"元ファイル: {names}")
    if form.get("匿名化済み"):
        lines.append("**匿名化加工済みデータとして処理しました。**")
    warn = form.get("注意") or []
    if warn:
        lines.append("")
        lines.append("> **注意**")
        for w in warn:
            lines.append(f"> - {w}")
    lines.append("")
    lines.append("読み取りは機械によるものです。**必ず原本と照らして確かめてください。**")

    for sec in form.get("節") or []:
        lines.append("")
        lines.append(f"## {sec.get('表題', '')}")
        for item in sec.get("項目") or []:
            if "まとまり" in item:
                lines.append("")
                lines.append(f"### {item['まとまり']}")
                for sub in item.get("項目") or []:
                    lines.extend(_item_lines(sub))
            else:
                lines.extend(_item_lines(item))
    low = _count_low(form)
    lines.append("")
    lines.append(f"要確認の項目: {low} 個")
    return "\n".join(lines)


def _count_low(form: Dict[str, Any]) -> int:
    n = 0
    for sec in form.get("節") or []:
        for item in sec.get("項目") or []:
            children = item.get("項目") if "まとまり" in item else [item]
            for sub in children or []:
                if sub.get("確信度の段階") in ("低", "中"):
                    n += 1
    return n
