# -*- coding: utf-8 -*-
"""医療機関の一覧を厚生労働省（地方厚生局）から取得する。

各地方厚生局が「コード内容別医療機関一覧表」を Excel で公開している。
ここから 医療機関名・所在地・電話番号 を取り出し、都道府県ごとの JSON にする。

**局ごとに公開の仕方がまるで違う。**

| 局 | 形 | 名前 |
|---|---|---|
| 北海道 | xlsx 直リンク | `000495827.xlsx`（番号だけ） |
| 東北 | xlsx 直リンク | `shitei-touhoku-ika-r0808.xlsx`（局全体で1つ） |
| 関東信越 | zip | `shitei_ika_r0809.zip` |
| 東海北陸 | zip | `2609-01-01.zip`（番号だけ） |
| 近畿 | zip | `2026.9_kikanzentai_ika.zip`、中身は `..._osaka_ika.xlsx` |
| 中国四国 | zip | `000496913.zip`（番号だけ、リンク文字が「医科」） |
| 四国 | zip | `000495939.zip`（番号だけ、リンク文字も「（ZIP）」だけ） |
| 九州 | zip | 事務所ごとに1つ、97個並んでいる |

ファイル名からは判断できないので、**中身を見て判定する**。
Excel の先頭に `コード内容別医療機関一覧表` `[大阪府]` `[令和 8年 9月 1日現在 医科 現存/休止]`
と書かれているので、そこで都道府県と医科／歯科／薬局を見分ける。

URL は毎月変わるうえ、局のページ構成も変わる。固定せず、
一覧ページから探し、見つからなければ局のサイトを辿って探す。
"""
import argparse
import io
import json
import os
import re
import unicodedata
import urllib.parse
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "dict", "hospitals")
UA = ("Mozilla/5.0 (compatible; ikensho-ocr/0.1; "
      "+https://github.com/masarusanuki/ikensho-ocr)")
SITE = "https://kouseikyoku.mhlw.go.jp/"

# 局 → (一覧ページの候補, その局が扱う都道府県)
BUREAUS = {
    "hokkaido": dict(
        pages=["hokkaido/gyomu/gyomu/hoken_kikan/code_ichiran.html"],
        prefs=["北海道"]),
    "tohoku": dict(
        pages=["tohoku/gyomu/gyomu/hoken_kikan/itiran.html"],
        prefs=["青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県"]),
    "kantoshinetsu": dict(
        pages=["kantoshinetsu/chousa/shitei.html"],
        prefs=["茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都",
               "神奈川県", "新潟県", "山梨県", "長野県"]),
    "tokaihokuriku": dict(
        pages=["tokaihokuriku/newpage_00287.html"],
        prefs=["富山県", "石川県", "岐阜県", "静岡県", "愛知県", "三重県"]),
    "kinki": dict(
        pages=["kinki/tyousa/shinkishitei.html"],
        prefs=["福井県", "滋賀県", "京都府", "大阪府", "兵庫県", "奈良県", "和歌山県"]),
    "chugokushikoku": dict(
        pages=["chugokushikoku/chousaka/iryoukikanshitei.html"],
        prefs=["鳥取県", "島根県", "岡山県", "広島県", "山口県"]),
    "shikoku": dict(
        pages=["shikoku/gyomu/gyomu/hoken_kikan/shitei/index.html"],
        prefs=["徳島県", "香川県", "愛媛県", "高知県"]),
    "kyushu": dict(
        pages=["kyushu/gyomu/gyomu/hoken_kikan/index_00006.html"],
        prefs=["福岡県", "佐賀県", "長崎県", "熊本県", "大分県", "宮崎県",
               "鹿児島県", "沖縄県"]),
}

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
PREF_NAMES = list(PREF_BY_CODE.values())
# ファイル名がローマ字の局（近畿など）用
PREF_BY_ROMAJI = {
    "hokkaido": "北海道", "aomori": "青森県", "iwate": "岩手県", "miyagi": "宮城県",
    "akita": "秋田県", "yamagata": "山形県", "fukushima": "福島県", "ibaraki": "茨城県",
    "tochigi": "栃木県", "gunma": "群馬県", "saitama": "埼玉県", "chiba": "千葉県",
    "tokyo": "東京都", "kanagawa": "神奈川県", "niigata": "新潟県", "toyama": "富山県",
    "ishikawa": "石川県", "fukui": "福井県", "yamanashi": "山梨県", "nagano": "長野県",
    "gifu": "岐阜県", "shizuoka": "静岡県", "aichi": "愛知県", "mie": "三重県",
    "shiga": "滋賀県", "kyoto": "京都府", "osaka": "大阪府", "hyogo": "兵庫県",
    "nara": "奈良県", "wakayama": "和歌山県", "tottori": "鳥取県", "shimane": "島根県",
    "okayama": "岡山県", "hiroshima": "広島県", "yamaguchi": "山口県",
    "tokushima": "徳島県", "kagawa": "香川県", "ehime": "愛媛県", "kochi": "高知県",
    "fukuoka": "福岡県", "saga": "佐賀県", "nagasaki": "長崎県", "kumamoto": "熊本県",
    "oita": "大分県", "miyazaki": "宮崎県", "kagoshima": "鹿児島県", "okinawa": "沖縄県",
}

# 候補として見に行くファイルの上限（局ごと）
MAX_TRIES = 20
# 1ファイルの上限（これより大きいものは一覧表ではない）
MAX_BYTES = 60 * 1024 * 1024


def fetch(url, timeout=240):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return res.read()


def fetch_text(url, timeout=60):
    raw = fetch(url, timeout)
    for enc in ("utf-8", "cp932", "euc-jp"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "ignore")


def strip_tags(html):
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def candidates(page_url, html):
    """一覧表らしいファイルを、確からしい順に返す。

    ファイル名では判断できないので、リンクの文字と**その手前の文章**を見る。
    表の中に「医科（PDF） 歯科（PDF） 薬局（PDF） エクセルデータ（ZIP）」と
    並んでいることが多いため、直前の文脈が効く。
    """
    out = []
    for m in re.finditer(r'href="([^"#]+\.(?:zip|xlsx|xls))"[^>]*>(.*?)</a>',
                         html, re.I | re.S):
        href, label = m.group(1), strip_tags(m.group(2)).strip()
        before = strip_tags(html[max(0, m.start() - 700):m.start()])[-260:]
        ctx = label + " " + before
        score = 0.0
        if "医科" in label:
            score += 6
        elif "医科" in before:
            score += 2
        if re.search(r"(歯科|薬局|訪問看護|施術|柔道整復|あん摩)", label):
            score -= 8
        if "併設" in label:
            score -= 6
        if re.search(r"(新規|廃止|辞退|取消|失効|届出受理|平均点数|略称)", ctx):
            score -= 5
        if re.search(r"(コード内容別|指定一覧|一覧表|全体)", ctx):
            score += 3
        if href.lower().endswith(".zip"):
            score += 1                      # 都道府県がまとまっていることが多い
        if re.search(r"(ika|iryou?kikan|kikanzentai|shitei|code)", href, re.I):
            score += 1
        if re.search(r"(shika|sika|yakkyoku|heisetsu|heisetu|sinki|shinki|haishi)",
                     href, re.I):
            score -= 6
        # ページの上にあるものほど新しい
        score -= m.start() / max(len(html), 1) * 2
        out.append((score, urllib.parse.urljoin(page_url, href), label))
    out.sort(key=lambda x: -x[0])
    # 同じURLは1回だけ
    seen, uniq = set(), []
    for s, u, lab in out:
        if u in seen:
            continue
        seen.add(u)
        uniq.append((s, u, lab))
    return uniq


def discover_pages(bureau, verbose=False):
    """局のサイトを辿って、一覧表が置いてありそうなページを探す。

    設定したページが 404 になっても自力で見つけられるようにするための保険。
    """
    root = urllib.parse.urljoin(SITE, bureau + "/")
    seen, queue, found = {root}, [(root, 0)], []
    while queue and len(seen) < 40:
        url, depth = queue.pop(0)
        try:
            html = fetch_text(url)
        except Exception:
            continue
        if re.search(r"\.(zip|xlsx)\"", html) and \
                re.search(r"(コード内容別|指定一覧|一覧表)", strip_tags(html)):
            found.append(url)
        if depth >= 2:
            continue
        for m in re.finditer(r'href="([^"#]+\.html?)"[^>]*>(.*?)</a>', html, re.I | re.S):
            u = urllib.parse.urljoin(url, m.group(1))
            label = strip_tags(m.group(2))
            if not u.startswith(root) or u in seen:
                continue
            if re.search(r"(コード内容別|指定状況|指定一覧|一覧|医療機関)", label) or \
                    re.search(r"(hoken_kikan|shitei|chousa|tyousa|ichiran|itiran)", u, re.I):
                seen.add(u)
                queue.append((u, depth + 1))
    if verbose and found:
        print("      （自動で見つけたページ: " + ", ".join(found[:3]) + "）")
    return found


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


def pref_from_name(filename):
    """ファイル名から都道府県を求める（中身で分からなかったときの保険）。"""
    base = os.path.basename(filename)
    m = re.search(r"(?:^|[^0-9])(\d{2})(?:[^0-9]|$)", base)
    if m and m.group(1) in PREF_BY_CODE:
        return PREF_BY_CODE[m.group(1)]
    for name in PREF_NAMES:
        if name.rstrip("都道府県") in base:
            return name
    low = base.lower()
    for romaji, name in PREF_BY_ROMAJI.items():
        if romaji in low:
            return name
    return ""


def parse_sheet(ws, filename="", default_pref=""):
    """1シートを読み、(都道府県, 明細) を返す。一覧表でなければ (None, []) 。"""
    rows, head = [], []
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        cells = [clean(c) for c in (row or [])][:9]
        if i < 12:
            head.append(" ".join(c for c in cells if c))
        rows.append(cells)

    header = " ".join(head)
    if "コード内容別" not in header and "医療機関一覧" not in header:
        return None, [], ""
    if "併設" in header:
        return None, [], ""                 # 医科併設は歯科側の一覧なので除く
    if "医科" not in header:
        return None, [], ""                 # 歯科・薬局・訪問看護は対象外

    # 都道府県は、①表題の [○○県] ②シート名 ③ファイル名 ④局が1県だけ の順で決める
    pref = ""
    m = re.search(r"[\[［]\s*(" + "|".join(PREF_NAMES) + r")\s*[\]］]", header)
    if m:
        pref = m.group(1)
    if not pref and ws.title in PREF_NAMES:
        pref = ws.title
    if not pref:
        pref = pref_from_name(filename) or default_pref
    if not pref:
        return None, [], ""

    # 「[令和 8年 8月 1日現在 医科 現存/休止]」から基準日を取る。
    # 局によっては過去の月のファイルも同じページに並ぶので、
    # 新しい月のものだけを残すために使う。
    as_of = ""
    md = re.search(r"(令和|平成)\s*(\d+)\s*年\s*(\d+)\s*月\s*(\d+)\s*日現在", header)
    if md:
        era_base = 2018 if md.group(1) == "令和" else 1988
        as_of = (f"{era_base + int(md.group(2)):04d}-"
                 f"{int(md.group(3)):02d}-{int(md.group(4)):02d}")

    out = []
    for i, cells in enumerate(rows):
        if len(cells) < 5:
            continue
        no, code, name, addr, tel = cells[0], cells[1], cells[2], cells[3], cells[4]
        if not (no.isdigit() and name and addr.startswith("〒")):
            continue
        status = ""
        if i + 1 < len(rows):
            status = next((c for c in rows[i + 1][:4] if c in ("現存", "休止", "廃止")), "")
        if status == "廃止":
            continue
        postal, address = split_address(addr)
        out.append(dict(name=name, address=address, postal=postal,
                        phone=clean(tel), code=code,
                        pref=pref, status=status or "現存", as_of=as_of))
    return pref, out, as_of


def parse_workbook(data, filename="", default_pref=""):
    """Excel を読み、{都道府県: 明細} を返す。

    局によっては**1つのファイルにシートが県ごとに並ぶ**（東北）ので、
    先頭シートだけでなく全部のシートを見る。
    """
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    got = {}
    try:
        for title in wb.sheetnames:
            pref, items, as_of = parse_sheet(wb[title], filename, default_pref)
            if pref and items:
                got.setdefault(pref, {}).setdefault(as_of, []).extend(items)
    finally:
        wb.close()
    return got


def harvest(url, default_pref="", verbose=True):
    """URL（zip か xlsx）を取り、都道府県ごとの明細を返す。"""
    blob = fetch(url)
    if len(blob) > MAX_BYTES:
        return {}
    got = {}
    if url.lower().endswith(".zip"):
        try:
            z = zipfile.ZipFile(io.BytesIO(blob))
        except Exception:
            return {}
        for name in z.namelist():
            if not name.lower().endswith((".xlsx", ".xls")):
                continue
            try:
                disp = name.encode("cp437").decode("cp932")
            except Exception:
                disp = name
            try:
                for pref, byday in parse_workbook(z.read(name), disp,
                                                  default_pref).items():
                    for as_of, items in byday.items():
                        got.setdefault(pref, {}).setdefault(as_of, []).extend(items)
            except Exception as exc:
                if verbose:
                    print(f"        ! {os.path.basename(disp)}: {exc}")
    else:
        try:
            got = parse_workbook(blob, url, default_pref)
        except Exception as exc:
            if verbose:
                print(f"        ! {os.path.basename(url)}: {exc}")
            return {}
    return got


def collect(bureau, conf, verbose=True, progress=None):
    """1つの局から、担当する都道府県ぶんを集める。

    `progress` を渡すと、どこまで進んだかを都度知らせる（画面に出すため）。
    """
    def notify(**kw):
        if progress:
            try:
                progress(dict(bureau=bureau, **kw))
            except Exception:
                pass
    want = set(conf["prefs"])
    # 1県しか扱わない局（北海道）は、表に県名が書かれていないことがある
    only_pref = conf["prefs"][0] if len(conf["prefs"]) == 1 else ""
    pages = [urllib.parse.urljoin(SITE, p) for p in conf["pages"]]
    # 都道府県 → 基準日 → 明細。北海道のように病院と診療所でファイルが分かれる局が
    # あるので、同じ基準日のものは足し合わせる。古い月のものは捨てる。
    pool, errors, tried = {}, [], 0

    def scan(page_list):
        nonlocal tried
        for page in page_list:
            notify(message=f"{bureau}: 一覧ページを見ています")
            try:
                html = fetch_text(page)
            except Exception as exc:
                errors.append(f"{bureau}: {page} を開けません（{exc}）")
                continue
            cands = candidates(page, html)
            top = cands[0][0] if cands else 0
            for score, url, label in cands:
                if score <= 0 or tried >= MAX_TRIES:
                    break
                # まだ足りない県があるうちは続ける。足りていても、
                # 同じくらい確からしいファイル（同じ表の中の別ファイル）は見る。
                # 北海道のように「病院」と「診療所」でファイルが分かれる局があるため。
                if not (want - set(pool)) and score < top - 1.0:
                    break
                tried += 1
                try:
                    got = harvest(url, only_pref, verbose)
                except Exception as exc:
                    errors.append(f"{bureau}: {os.path.basename(url)} 取得失敗（{exc}）")
                    continue
                got = {p: v for p, v in got.items() if p in want}
                if not got and verbose:
                    print(f"      － {os.path.basename(url)}"
                          f"（{label[:14]}）は一覧表ではありませんでした")
                for p, byday in got.items():
                    for as_of, items in byday.items():
                        pool.setdefault(p, {}).setdefault(as_of, []).extend(items)
                        if verbose:
                            print(f"      {p:6s} {len(items):5d} 件  "
                                  f"{as_of or '日付不明'}  ← {os.path.basename(url)}")
                        notify(pref=p, count=len(items), as_of=as_of,
                               message=f"{p} {len(items):,} 件")
                # 九州のように過去の月のファイルが同じページに並ぶ局がある。
                # ほしい県が最新の基準日で揃っていて、しかも**今読んだものが
                # 古い基準日だった**なら、以降は古いものしか無いので終わり。
                days = {d for byday in pool.values() for d in byday if d}
                newest = max(days) if days else ""
                this_day = max((d for byday in got.values() for d in byday if d),
                               default="")
                if (newest and this_day and this_day < newest
                        and not (want - {p for p, byday in pool.items()
                                         if newest in byday})):
                    return
            if not (want - set(pool)):
                return

    scan(pages)
    if want - set(pool):
        # 設定したページで足りなければ、局のサイトを辿って探す
        if verbose:
            print(f"      {'、'.join(sorted(want - set(pool)))} が見つからないので"
                  f"ページを探します…")
        scan(discover_pages(bureau, verbose))

    # 県ごとに、いちばん新しい基準日のものだけを採る
    found = {}
    for pref, byday in pool.items():
        newest = sorted(byday)[-1]
        found[pref] = byday[newest]
        dropped = sum(len(v) for k, v in byday.items() if k != newest)
        if dropped and verbose:
            print(f"      {pref}: 古い基準日の {dropped} 件は使いません")

    missing = sorted(want - set(found))
    if missing:
        errors.append(f"{bureau}: {'、'.join(missing)} を取得できませんでした")
    return found, errors


def run(bureaus=None, out_dir=OUT_DIR, verbose=True, progress=None):
    os.makedirs(out_dir, exist_ok=True)
    targets = bureaus or list(BUREAUS)
    by_pref, errors = {}, []
    for key in targets:
        conf = BUREAUS.get(key)
        if not conf:
            continue
        if verbose:
            print(f"  {key}")
        if progress:
            try:
                progress(dict(bureau=key, message=f"{key} を取得しています"))
            except Exception:
                pass
        got, errs = collect(key, conf, verbose, progress)
        errors.extend(errs)
        for pref, items in got.items():
            by_pref.setdefault(pref, []).extend(items)

    import datetime
    updated = datetime.datetime.now().astimezone().isoformat()
    # 取れなかった都道府県は、前回の内容を残す（更新に失敗して消えるのを避ける）
    kept = 0
    for pref in PREF_NAMES:
        if pref in by_pref:
            continue
        path = os.path.join(out_dir, f"{pref}.json")
        if os.path.exists(path):
            kept += 1
    index = []
    as_of_by_pref = {}
    for pref, items in by_pref.items():
        days = {h.pop("as_of", "") for h in items} - {""}
        as_of_by_pref[pref] = max(days) if days else ""
    for pref, items in sorted(by_pref.items()):
        seen = set()
        uniq = []
        for h in sorted(items, key=lambda h: h["name"]):
            key = (h["name"], h["address"], h["code"])
            if key in seen:
                continue
            seen.add(key)
            uniq.append(h)
        path = os.path.join(out_dir, f"{pref}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(dict(pref=pref, updated=updated,
                           as_of=as_of_by_pref.get(pref, ""),
                           count=len(uniq), entries=uniq), fh, ensure_ascii=False)
        index.append(dict(pref=pref, count=len(uniq), updated=updated,
                          as_of=as_of_by_pref.get(pref, "")))
    # 今回取れなかったぶんも索引には残す
    for pref in PREF_NAMES:
        if pref in by_pref:
            continue
        path = os.path.join(out_dir, f"{pref}.json")
        if not os.path.exists(path):
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                old = json.load(fh)
            index.append(dict(pref=pref, count=old.get("count", 0),
                              updated=old.get("updated", ""),
                              as_of=old.get("as_of", "")))
        except Exception:
            continue
    index.sort(key=lambda x: PREF_NAMES.index(x["pref"]))
    with open(os.path.join(out_dir, "index.json"), "w", encoding="utf-8") as fh:
        json.dump(dict(updated=updated,
                       source="厚生労働省 地方厚生局「コード内容別医療機関一覧表」",
                       prefectures=index, errors=errors), fh,
                  ensure_ascii=False, indent=1)
    total = sum(i["count"] for i in index)
    if verbose:
        print(f"\n{len(index)} 都道府県 / 合計 {total:,} 件"
              + (f"（うち {kept} 県は前回のまま）" if kept else "")
              + f": {out_dir}")
        for e in errors:
            print("  ! " + e)
    return dict(prefectures=len(index), total=total, errors=errors)


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
