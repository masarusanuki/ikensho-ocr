# -*- coding: utf-8 -*-
"""医療機関の一覧を厚生労働省（地方厚生局）から取得する。

各地方厚生局が「コード内容別医療機関一覧表」を都道府県ごとの Excel で公開している。
ここから 医療機関名・所在地・電話番号 を取り出し、都道府県ごとの JSON にする。

ファイル名に年月が入っており毎月変わるので、URLを固定せず
一覧ページから最新のものを探す。「最新版に更新」で何度でも取り直せる。
"""
import argparse
import io
import json
import os
import re
import sys
import unicodedata
import urllib.parse
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "dict", "hospitals")
UA = "Mozilla/5.0 (compatible; ikensho-ocr/0.1; +https://github.com/masarusanuki/ikensho-ocr)"

# 地方厚生局と、その一覧ページ
BUREAUS = {
    "hokkaido": "https://kouseikyoku.mhlw.go.jp/hokkaido/gyomu/gyomu/hoken_kikan/index.html",
    "tohoku": "https://kouseikyoku.mhlw.go.jp/tohoku/gyomu/gyomu/hoken_kikan/index.html",
    "kantoshinetsu": "https://kouseikyoku.mhlw.go.jp/kantoshinetsu/chousa/shitei.html",
    "tokaihokuriku": "https://kouseikyoku.mhlw.go.jp/tokaihokuriku/newpage_00073.html",
    "kinki": "https://kouseikyoku.mhlw.go.jp/kinki/tyousa/shitei_kikan.html",
    "chugoku": "https://kouseikyoku.mhlw.go.jp/chugokushikoku/chousa/shitei.html",
    "shikoku": "https://kouseikyoku.mhlw.go.jp/shikoku/gyomu/gyomu/hoken_kikan/index.html",
    "kyushu": "https://kouseikyoku.mhlw.go.jp/kyushu/gyomu/gyomu/hoken_kikan/index.html",
}

# 都道府県コード（ファイル名の先頭3桁の上2桁）
PREF_BY_CODE = {
    "01": "北海道", "02": "青森県", "03": "岩手県", "04": "宮城県", "05": "秋田県",
    "06": "山形県", "07": "福島県", "08": "茨城県", "09": "栃木県", "10": "群馬県",
    "11": "埼玉県", "12": "千葉県", "13": "東京都", "14": "神奈川県", "15": "新潟県",
    "16": "富山県", "17": "石川県", "18": "福井県", "19": "山梨県", "20": "長野県",
    "21": "岐阜県", "22": "静岡県", "23": "愛知県", "24": "三重県", "25": "滋賀県",
    "26": "京都府", "27": "大阪府", "28": "兵庫県", "29": "奈良県", "30": "和歌山県",
    "31": "鳥取県", "32": "島根県", "33": "岡山県", "34": "広島県", "35": "山口県",
    "36": "徳島県", "37": "香川県", "38": "愛媛県", "39": "高知県", "40": "福岡県",
    "41": "佐賀県", "42": "長崎県", "43": "熊本県", "44": "大分県", "45": "宮崎県",
    "46": "鹿児島県", "47": "沖縄県",
}
PREF_NAMES = set(PREF_BY_CODE.values())


def fetch(url, timeout=180):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return res.read()


def find_zip(index_url):
    """一覧ページから「医科」の指定一覧 zip の URL を探す（最新のもの）。"""
    try:
        html = fetch(index_url, timeout=60).decode("utf-8", "ignore")
    except Exception as exc:
        return None, f"一覧ページを取得できません（{exc}）"
    cands = re.findall(r'href="([^"]*shitei[^"]*ika[^"]*\.zip)"', html, re.I)
    cands = [c for c in cands if "heisetsu" not in c and "shika" not in c]
    if not cands:
        return None, "医科の一覧ファイルが見つかりません"
    # 末尾の年月が新しいものを採る
    def key(u):
        m = re.search(r"r(\d{4})", u)
        return m.group(1) if m else ""
    best = sorted(cands, key=key)[-1]
    return urllib.parse.urljoin(index_url, best), None


def clean(text):
    if text is None:
        return ""
    return unicodedata.normalize("NFKC", str(text)).replace("　", " ").strip()


def split_address(raw):
    """「〒400－0073甲府市湯村三丁目１－８」を郵便番号と住所に分ける。"""
    t = clean(raw)
    m = re.match(r"^〒?\s*(\d{3})\s*[-‐－ー]?\s*(\d{4})\s*(.*)$", t)
    if m:
        return f"{m.group(1)}-{m.group(2)}", m.group(3).strip()
    return "", t


def parse_workbook(data, pref):
    """Excel から 医療機関名・住所・電話 を取り出す。"""
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]
    rows = list(ws.iter_rows(values_only=True))
    out = []
    for i, row in enumerate(rows):
        cells = [clean(c) for c in (row or [])][:8]
        if len(cells) < 5:
            continue
        no, code, name, addr, tel = cells[0], cells[1], cells[2], cells[3], cells[4]
        if not (no.isdigit() and name and addr.startswith("〒")):
            continue
        status = ""
        if i + 1 < len(rows):
            nxt = [clean(c) for c in (rows[i + 1] or [])][:4]
            status = next((c for c in nxt if c in ("現存", "休止", "廃止")), "")
        if status in ("廃止",):
            continue
        postal, address = split_address(addr)
        out.append(dict(name=name, address=address, postal=postal,
                        phone=clean(tel), code=code,
                        pref=pref, status=status or "現存"))
    wb.close()
    return out


def pref_of(filename):
    """ファイル名の先頭コードから都道府県を求める。"""
    base = os.path.basename(filename)
    m = re.match(r"(\d{2})\d", base)
    if m and m.group(1) in PREF_BY_CODE:
        return PREF_BY_CODE[m.group(1)]
    for name in PREF_NAMES:
        if name.rstrip("都道府県") in base:
            return name
    return ""


def run(bureaus=None, out_dir=OUT_DIR, verbose=True):
    os.makedirs(out_dir, exist_ok=True)
    targets = bureaus or list(BUREAUS)
    by_pref, errors = {}, []
    for key in targets:
        url = BUREAUS.get(key)
        if not url:
            continue
        zurl, err = find_zip(url)
        if not zurl:
            errors.append(f"{key}: {err}")
            if verbose:
                print(f"  {key:16s} × {err}")
            continue
        if verbose:
            print(f"  {key:16s} → {os.path.basename(zurl)}")
        try:
            blob = fetch(zurl)
            z = zipfile.ZipFile(io.BytesIO(blob))
        except Exception as exc:
            errors.append(f"{key}: 取得に失敗（{exc}）")
            continue
        for name in z.namelist():
            if not name.lower().endswith(".xlsx"):
                continue
            try:
                disp = name.encode("cp437").decode("cp932")
            except Exception:
                disp = name
            pref = pref_of(disp)
            if not pref:
                continue
            try:
                items = parse_workbook(z.read(name), pref)
            except Exception as exc:
                errors.append(f"{pref}: 解析に失敗（{exc}）")
                continue
            by_pref.setdefault(pref, []).extend(items)
            if verbose:
                print(f"      {pref:6s} {len(items):5d} 件")

    import datetime
    updated = datetime.datetime.now().astimezone().isoformat()
    index = []
    for pref, items in sorted(by_pref.items()):
        items.sort(key=lambda h: h["name"])
        path = os.path.join(out_dir, f"{pref}.json")
        json.dump(dict(pref=pref, updated=updated, count=len(items), entries=items),
                  open(path, "w", encoding="utf-8"), ensure_ascii=False)
        index.append(dict(pref=pref, count=len(items)))
    json.dump(dict(updated=updated, source="厚生労働省 地方厚生局「コード内容別医療機関一覧表」",
                   prefectures=index, errors=errors),
              open(os.path.join(out_dir, "index.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    if verbose:
        total = sum(i["count"] for i in index)
        print(f"\n{len(index)} 都道府県 / 合計 {total} 件を書き出しました: {out_dir}")
        for e in errors:
            print("  ! " + e)
    return dict(prefectures=len(index), total=sum(i["count"] for i in index), errors=errors)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bureaus", nargs="*", choices=list(BUREAUS),
                    help="取得する地方厚生局（既定: すべて）")
    ap.add_argument("--out", default=OUT_DIR)
    args = ap.parse_args()
    print("厚生労働省（地方厚生局）から医療機関一覧を取得します")
    run(args.bureaus, args.out)


if __name__ == "__main__":
    main()
