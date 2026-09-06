# -*- coding: utf-8 -*-
"""テキスト欄の座標を確定させる。

  1. チェックボックスを基準にした配置定義（tools/text_placement.py）
  2. 様式ごとの実測値（templates/measured/<id>.json）
の順に適用する。どちらにも無い項目は、公式様式からの機械的な転写のまま
「暫定」として残し、確認画面で注意を出す。
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from text_placement import PLACEMENT, box_map, resolve  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def apply_to(tid, dry_run=False):
    path = os.path.join(ROOT, "templates", f"{tid}.json")
    tpl = json.load(open(path, encoding="utf-8"))
    mpath = os.path.join(ROOT, "templates", "measured", f"{tid}.json")
    measured = json.load(open(mpath, encoding="utf-8")) if os.path.exists(mpath) else {}

    # 欠落しているテキスト欄を公式様式から補う（過去の処理で落ちた項目の復元）
    master = json.load(open(os.path.join(ROOT, "templates", "official_v1.json"),
                            encoding="utf-8"))
    restored = 0
    for page in tpl["pages"]:
        mpage = next((p for p in master["pages"] if p["index"] == page["index"]), None)
        if not mpage:
            continue
        have = {t["field"] for t in page["texts"]}
        for mt in mpage["texts"]:
            if mt["field"] in have:
                continue
            page["texts"].append(dict(field=mt["field"], type=mt["type"],
                                      rect=list(mt["rect"]),
                                      options=mt.get("options"),
                                      charset=mt.get("charset", ""),
                                      pii=mt.get("pii", ""),
                                      kind=mt.get("kind", ""),
                                      era_field=mt.get("era_field", ""),
                                      default_era=mt.get("default_era", ""),
                                      always_pick=bool(mt.get("always_pick")),
                                      transferred=True))
            restored += 1
    if restored:
        print(f"  欠落していた {restored} 個のテキスト欄を復元しました")

    # 公式様式は座標の出どころが確かなので、規則で置き換えず既存を尊重する
    is_reference = tid == "official_v1"
    stats = dict(rule=0, measured=0, provisional=0)
    for page in tpl["pages"]:
        pi = page["index"]
        bm = box_map(page)
        mrects = measured.get(f"page{pi}", {})
        for t in page["texts"]:
            fid = t["field"]
            if fid in mrects:
                t["rect"] = [round(v, 6) for v in mrects[fid]]
                t["placement"] = "実測"
                t.pop("transferred", None)
                stats["measured"] += 1
                continue
            r = None if is_reference else (resolve(fid, page, bm) if fid in PLACEMENT else None)
            if r:
                t["rect"] = r
                t["placement"] = "チェックボックス基準"
                t.pop("transferred", None)
                stats["rule"] += 1
                continue
            if is_reference:
                # 公式様式は目視確認済みの定義（tools/form_definition.py）が正
                t["placement"] = "検証済み"
                t.pop("transferred", None)
                stats["measured"] += 1
            else:
                t["placement"] = "暫定"
                t["transferred"] = True
                stats["provisional"] += 1

    # 日付欄の小枠（年・月・日）を、公式様式での相対位置からこの様式へ写す。
    # 区切り文字の位置は様式によらず「年」「月」「日」の順なので、
    # 欄の幅に対する割合で置き換えれば十分な精度になる。
    for page in tpl["pages"]:
        mpage = next((p for p in master["pages"] if p["index"] == page["index"]), None)
        if not mpage:
            continue
        mslots = {t["field"]: (t["rect"], t.get("slots"))
                  for t in mpage["texts"] if t.get("slots")}
        for t in page["texts"]:
            src = mslots.get(t["field"])
            if not src:
                continue
            (mx, my, mw, mh), slots = src
            x, y, w, h = t["rect"]
            out = {}
            for key, r in (slots or {}).items():
                rel0 = (r[0] - mx) / mw
                rel1 = (r[0] + r[2] - mx) / mw
                out[key] = [round(x + rel0 * w, 6), round(y, 6),
                            round((rel1 - rel0) * w, 6), round(h, 6)]
            if out:
                t["slots"] = out

    for page in tpl["pages"]:
        page["texts"].sort(key=lambda t: (round(t["rect"][1], 3), t["rect"][0]))
    print(f"{tid}: 実測 {stats['measured']} / チェックボックス基準 {stats['rule']} / "
          f"暫定 {stats['provisional']}")
    if not dry_run:
        json.dump(tpl, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"  更新: {path}")
    return stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*", default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    ids = args.ids or [f[:-5] for f in sorted(os.listdir(os.path.join(ROOT, "templates")))
                       if f.endswith(".json")]
    for tid in ids:
        apply_to(tid, args.dry_run)


if __name__ == "__main__":
    main()
