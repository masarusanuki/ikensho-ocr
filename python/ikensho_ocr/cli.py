# -*- coding: utf-8 -*-
"""コマンドライン。

  ikensho extract  読み取ってJSON/CSVに出力する
  ikensho serve    確認・編集画面をローカルで開く
  ikensho info     動作環境と様式テンプレートの状況を表示する
"""
import argparse
import glob
import os
import sys

from . import __version__
from .export import write_csv, write_form_json, write_json
from .extract import extract_record
from .ocr import available_engines
from .schema import load_schema
from .templates import load_templates


def _expand(patterns):
    out = []
    for p in patterns:
        hits = sorted(glob.glob(p)) if any(c in p for c in "*?[") else [p]
        out.extend(hits)
    return [p for p in out if os.path.isfile(p)]


def _group_by_record(paths, group):
    """入力を1件ずつのまとまりに分ける。"""
    if group == "all":
        return [paths]
    if group == "file":
        return [[p] for p in paths]
    # pair: PDFは1ファイル1件、画像は2枚で1件とみなす
    groups, buf = [], []
    for p in paths:
        if os.path.splitext(p)[1].lower() == ".pdf":
            if buf:
                groups.append(buf)
                buf = []
            groups.append([p])
        else:
            buf.append(p)
            if len(buf) == 2:
                groups.append(buf)
                buf = []
    if buf:
        groups.append(buf)
    return groups


def cmd_extract(args):
    schema = load_schema(args.schema) if args.schema else load_schema()
    templates = load_templates(args.templates)
    paths = _expand(args.inputs)
    if not paths:
        sys.exit("入力ファイルが見つかりません")

    groups = _group_by_record(paths, args.group)
    print(f"{len(paths)} ファイル / {len(groups)} 件として読み取ります", file=sys.stderr)

    records = []
    for i, g in enumerate(groups, 1):
        names = "、".join(os.path.basename(p) for p in g)
        print(f"  [{i}/{len(groups)}] {names}", file=sys.stderr)
        rec = extract_record(g, schema=schema, templates=templates,
                             engine=args.engine, dpi=args.dpi,
                             anonymized=args.anonymized,
                             read_labels=args.labels,
                             use_llm=args.llm, llm_model=args.llm_model,
                             llm_budget=args.llm_budget)
        for w in rec.warnings:
            print(f"      ! {w}", file=sys.stderr)
        records.append(rec)

    if args.json:
        write_json(records, schema, args.json)
        print(f"JSON を書き出しました: {args.json}", file=sys.stderr)
    if args.csv:
        write_csv(records, schema, args.csv)
        print(f"CSV を書き出しました: {args.csv}", file=sys.stderr)
    if args.form_json:
        write_form_json(records, schema, args.form_json)
        print(f"様式の形の JSON を書き出しました: {args.form_json}", file=sys.stderr)
    if not args.json and not args.csv and not args.form_json:
        import json as _json
        from .export import record_to_json
        _json.dump(dict(count=len(records),
                        records=[record_to_json(r, schema) for r in records]),
                   sys.stdout, ensure_ascii=False, indent=2)
        print()

    low = sum(1 for r in records for e in r.fields.values()
              if e.get("level") in ("low", "medium"))
    print(f"要確認の項目: {low} 個。確認・編集画面は `ikensho serve` で開けます。",
          file=sys.stderr)


def cmd_serve(args):
    from .server import serve
    serve(host=args.host, port=args.port, open_browser=not args.no_browser,
          template_dir=args.templates, schema_path=args.schema,
          allow_origins=args.allow_origin)


def cmd_info(args):
    schema = load_schema(args.schema) if args.schema else load_schema()
    templates = load_templates(args.templates)
    print(f"テンプレートの置き場: {args.templates or os.environ.get('IKENSHO_TEMPLATES') or '(既定)'}")
    print(f"ikensho-ocr {__version__}")
    print(f"項目定義: v{schema.version} / {len(schema.order)} 項目")
    print("様式テンプレート:")
    for t in templates.values():
        boxes = sum(len(p.boxes) for p in t.pages)
        texts = sum(len(p.texts) for p in t.pages)
        print(f"  - {t.id}: {t.name} / {t.page_count}ページ / "
              f"チェックボックス{boxes}個 / テキスト欄{texts}個")
    print(f"利用可能なOCRエンジン: {', '.join(available_engines())}")
    from .llm import LlmAssist
    model = LlmAssist._find_model()
    try:
        import llama_cpp  # noqa: F401
        runtime = "あり"
    except Exception:
        runtime = "なし"
    from .llm import available as llm_available
    state = "有効（既定で使用）" if llm_available() else "無効"
    print(f"LLM候補提示: {state} / 実行環境={runtime} / モデル={model or '未配置'}")


def build_parser():
    ap = argparse.ArgumentParser(prog="ikensho", description="主治医意見書 読み取り")
    ap.add_argument("--version", action="version", version=__version__)
    ap.add_argument("--templates", metavar="DIR",
                    help="様式テンプレートの置き場（既定: リポジトリ内の templates/。"
                         "環境変数 IKENSHO_TEMPLATES でも指定できる）")
    ap.add_argument("--schema", metavar="FILE", help="項目定義JSONの場所")
    sub = ap.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("extract", help="ファイルを読み取って出力する")
    e.add_argument("inputs", nargs="+", help="PDF・画像ファイル（ワイルドカード可）")
    e.add_argument("--json", help="JSON の出力先")
    e.add_argument("--csv", help="CSV の出力先")
    e.add_argument("--form-json", dest="form_json",
                   help="様式（PDF）の並びそのままの JSON の出力先。"
                        "チェック欄は印の付いた言葉で返す")
    e.add_argument("--engine", default="auto",
                   help="OCRエンジン (auto/ensemble/tesseract/rapidocr/vlm/none)。"
                        "ensemble は複数エンジンを併用し精度を上げるが時間は倍かかる。"
                        "vlm は画像を見て答えるLLMで読む"
                        "（models/vlm に要取得。遅いが手書きに別の当たり方をする）")
    e.add_argument("--dpi", type=int, default=200)
    e.add_argument("--llm", dest="llm", action="store_true", default=None,
                   help="小型LLMで読み取り候補を提示する（既定: 使える環境なら自動で有効）")
    e.add_argument("--no-llm", dest="llm", action="store_false",
                   help="LLMによる候補提示を使わない（最も速い）")
    e.add_argument("--llm-budget", type=int, default=8,
                   help="1件あたりのLLM呼び出し上限（既定8）")
    e.add_argument("--llm-model", help="GGUFモデルのパス（既定: models/ 内の .gguf）")
    e.add_argument("--no-labels", dest="labels", action="store_false", default=True,
                   help="チェック欄の後ろの言葉をOCRで確かめない（そのぶん速い）")
    e.add_argument("--anonymized", action="store_true",
                   help="匿名化加工済みデータとして扱う（住所・連絡先をマスク済みにする）")
    e.add_argument("--group", choices=["pair", "file", "all"], default="pair",
                   help="1件のまとめ方: pair=PDF1件/画像2枚1件, file=1ファイル1件, all=全部で1件")
    e.set_defaults(func=cmd_extract)

    s = sub.add_parser("serve", help="確認・編集画面をローカルで開く")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--no-browser", action="store_true")
    s.add_argument("--allow-origin", action="append", default=[],
                   metavar="URL",
                   help="別の場所に置いたページからこのAPIを呼ばせる"
                        "（例: --allow-origin http://localhost）。"
                        "公開したページから VLM を使うときに指定する。"
                        "許した場所のページはこの端末の読み取りAPIを使えるので、"
                        "信用できる場所だけを書くこと")
    s.set_defaults(func=cmd_serve)

    i = sub.add_parser("info", help="動作環境を表示する")
    i.set_defaults(func=cmd_info)
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
