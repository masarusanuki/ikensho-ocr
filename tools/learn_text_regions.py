# -*- coding: utf-8 -*-
"""テキスト欄の座標を、様式の枠（罫線）に合わせて確定させる。

考え方:
  記入する場所は罫線で決まっている。座標を推測するのではなく、
  検出した枠にスナップさせるのが最も確実。
  手順は
    1. 公式様式の欄の位置を、検証済みのチェックボックス186個の対応から
       おおよその位置に写す（どの欄がどのあたりか、の当たりを付けるだけ）
    2. その位置を、対象様式で検出した枠（行と縦罫線）にスナップして確定させる
    3. 記入済みサンプルのインク分布と突き合わせて、妥当か検証する
  推測に使うのは 1 だけで、最終的な座標は 2 の実測値になる。
"""
import argparse
import glob
import json
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_consensus_template as B  # noqa: E402
from form_grid import build_grid, merge_coords  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

HEAT_MIN = 0.10          # 何割のサンプルでインクが乗れば「記入あり」とみなすか
ROW_OVERLAP_MIN = 0.25   # 行にスナップする際に必要な重なり
INSET_Y = 0.14           # 行の上下からどれだけ内側に入れるか（行高比）


# ------------------------------------------------------------ ヒートマップ
def build_heatmap(page, blank, files, dpi=200):
    """記入済みサンプルを重ね、インクが乗る頻度の地図を作る。検証に使う。"""
    H, W = blank.shape
    base = cv2.dilate(
        cv2.adaptiveThreshold(blank, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                              cv2.THRESH_BINARY_INV, 31, 12),
        np.ones((3, 3), np.uint8), iterations=1)
    acc = np.zeros((H, W), np.float32)
    used = 0
    for f in files:
        img = B.load_page(f, page["index"] - 1, dpi)
        if img is None:
            continue
        w = B.align_to(img, blank)
        if w is None:
            continue
        scan = cv2.adaptiveThreshold(w, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                                     cv2.THRESH_BINARY_INV, 31, 12)
        diff = cv2.morphologyEx(cv2.bitwise_and(scan, cv2.bitwise_not(base)),
                                cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
        acc += (diff > 0)
        used += 1
    return acc / max(used, 1), used


# ------------------------------------------------------------ 位置の当たり付け
def approx_map(mpage, page):
    """検証済みのチェックボックス対応から、おおよその座標変換を作る。

    y は全体を単調な折れ線で、x は近い行の対応点だけで直線近似する
    （build_consensus_template.RowLocalMap と同じ考え方）。
    """
    mW, mH = mpage["width"], mpage["height"]
    dW, dH = page["width"], page["height"]
    key = {(b["field"], b["opt"]): b["rect"] for b in mpage["boxes"]}
    src, dst = [], []
    for b in page["boxes"]:
        r = key.get((b["field"], b["opt"]))
        if not r:
            continue
        src.append([(r[0] + r[2] / 2) * mW, (r[1] + r[3] / 2) * mH])
        dst.append([(b["rect"][0] + b["rect"][2] / 2) * dW,
                    (b["rect"][1] + b["rect"][3] / 2) * dH])
    if len(src) < 8:
        return None
    return B.RowLocalMap(src, dst), (mW, mH), (dW, dH)


# ------------------------------------------------------------ 行の対応付け
def row_signature(grid, page):
    """枠の各行に、その行に含まれるチェックボックスの個数を付ける。

    チェックボックス186個の対応は検証済みなので、その個数の並びは
    2つの様式で一致する。これを手がかりに行同士を対応付ける。
    """
    W, H = page["width"], page["height"]
    boxes = [(b["rect"][1] + b["rect"][3] / 2) * H for b in page["boxes"]]
    out = []
    for r in grid["rows"]:
        n = sum(1 for y in boxes if r["top"] <= y <= r["bottom"])
        out.append(dict(top=r["top"], bottom=r["bottom"], cells=r["cells"], nbox=n))
    return out


def align_rows(a, b):
    """2つの行列を、順序を保ったまま対応付ける（動的計画法）。

    チェックボックスの個数が一致する行は強く結び付け、
    0個どうしの行は弱く結び付ける。片方にしかない行は飛ばす。
    """
    na, nb = len(a), len(b)
    NEG = -1e9
    dp = [[NEG] * (nb + 1) for _ in range(na + 1)]
    bt = [[None] * (nb + 1) for _ in range(na + 1)]
    dp[0][0] = 0.0
    for i in range(na + 1):
        for j in range(nb + 1):
            if dp[i][j] == NEG:
                continue
            if i < na and dp[i][j] - 0.6 > dp[i + 1][j]:
                dp[i + 1][j] = dp[i][j] - 0.6
                bt[i + 1][j] = ("skip_a", i, j)
            if j < nb and dp[i][j] - 0.6 > dp[i][j + 1]:
                dp[i][j + 1] = dp[i][j] - 0.6
                bt[i][j + 1] = ("skip_b", i, j)
            if i < na and j < nb:
                x, y = a[i]["nbox"], b[j]["nbox"]
                if x == y and x > 0:
                    score = 3.0 + min(x, 4) * 0.5
                elif x == y == 0:
                    score = 0.8
                elif abs(x - y) <= 1 and x > 0 and y > 0:
                    score = 0.5
                else:
                    score = -2.0
                # 相対的な縦位置が近いほど良い
                pa = (a[i]["top"] + a[i]["bottom"]) / 2 / max(a[-1]["bottom"], 1)
                pb = (b[j]["top"] + b[j]["bottom"]) / 2 / max(b[-1]["bottom"], 1)
                score -= abs(pa - pb) * 4.0
                if dp[i][j] + score > dp[i + 1][j + 1]:
                    dp[i + 1][j + 1] = dp[i][j] + score
                    bt[i + 1][j + 1] = ("match", i, j)
    pairs = []
    i, j = na, nb
    while bt[i][j] is not None:
        kind, pi_, pj_ = bt[i][j]
        if kind == "match":
            pairs.append((pi_, pj_))
        i, j = pi_, pj_
    pairs.reverse()
    return pairs


# ------------------------------------------------------------ 枠へのスナップ
def snap_rect(rect_px, grid, W, H):
    """おおよその矩形を、検出した枠にスナップして確定させる。

    上下は行の罫線に合わせ、左右はその行を横切る縦罫線で挟む。
    """
    x0, y0, x1, y1 = rect_px
    cy = (y0 + y1) / 2

    # --- 上下: 最もよく重なる行に合わせる
    best_row, best_ov = None, 0.0
    for r in grid["rows"]:
        ov = min(y1, r["bottom"]) - max(y0, r["top"])
        if ov <= 0:
            continue
        score = ov / max(y1 - y0, 1)
        if score > best_ov:
            best_row, best_ov = r, score
    if best_row is None:
        # 行に重ならない場合は、中心を含む行を探す
        for r in grid["rows"]:
            if r["top"] <= cy <= r["bottom"]:
                best_row, best_ov = r, 1.0
                break
    if best_row is None or best_ov < ROW_OVERLAP_MIN:
        return None, "枠に重なりません"

    top, bottom = best_row["top"], best_row["bottom"]
    inset = max(2, int((bottom - top) * INSET_Y))
    ny0, ny1 = top + inset, bottom - inset
    if ny1 - ny0 < 6:
        ny0, ny1 = top + 1, bottom - 1

    # --- 左右: その行を横切る縦罫線で挟む
    mid = (top + bottom) / 2
    xs = merge_coords([x for (x, vy0, vy1) in grid["vlines"]
                       if vy0 <= mid + 2 and vy1 >= mid - 2])
    left = max([x for x in xs if x <= x0 + (x1 - x0) * 0.25], default=None)
    right = min([x for x in xs if x >= x1 - (x1 - x0) * 0.25], default=None)
    nx0 = left + 3 if left is not None else max(0, int(x0))
    nx1 = right - 3 if right is not None else min(W, int(x1))
    if nx1 - nx0 < W * 0.02:
        nx0, nx1 = max(0, int(x0)), min(W, int(x1))
    return (nx0, ny0, nx1, ny1), None


def ink_clusters(heat, top, bottom, W, min_gap_ratio=0.020, min_w_ratio=0.018):
    """その行で実際に書かれている横方向の塊を求める。

    ヒートマップは白紙との差分なので、印刷された文字は含まれない。
    つまりここに出るのは記入された内容だけで、欄の横位置の実測値になる。
    """
    band = heat[max(0, int(top)):max(1, int(bottom))]
    if band.size == 0:
        return []
    cols = band.max(axis=0) >= HEAT_MIN
    gap = max(6, int(W * min_gap_ratio))
    minw = max(8, int(W * min_w_ratio))
    clusters, start, blank_run = [], None, 0
    for i, on in enumerate(cols):
        if on:
            if start is None:
                start = i
            blank_run = 0
        elif start is not None:
            blank_run += 1
            if blank_run >= gap:
                end = i - blank_run
                if end - start >= minw:
                    clusters.append((start, end))
                start, blank_run = None, 0
    if start is not None and len(cols) - start >= minw:
        clusters.append((start, len(cols) - 1))
    return clusters


# ------------------------------------------------------------ 本体
def learn(tid, pattern, limit=40, dpi=200, apply_changes=True, preview=None):
    tpl_path = os.path.join(ROOT, "templates", f"{tid}.json")
    tpl = json.load(open(tpl_path, encoding="utf-8"))
    master = json.load(open(os.path.join(ROOT, "templates", "official_v1.json"),
                            encoding="utf-8"))
    files = sorted(glob.glob(pattern))[:limit] if pattern else []
    print(f"様式 {tid} のテキスト欄を、枠に合わせて確定させます"
          + (f"（検証用サンプル {len(files)} 件）" if files else "（検証なし）"))

    stats = dict(snapped=0, refined=0, failed=0)
    for page in tpl["pages"]:
        pi = page["index"]
        mpage = next(p for p in master["pages"] if p["index"] == pi)
        blank_path = os.path.join(ROOT, "templates", "blanks",
                                  page.get("blank") or page["ref"])
        blank = cv2.imread(blank_path, cv2.IMREAD_GRAYSCALE)
        if blank is None:
            print(f"  page{pi}: 白紙様式が無いため飛ばします")
            continue
        if blank.shape != (page["height"], page["width"]):
            blank = cv2.resize(blank, (page["width"], page["height"]),
                               interpolation=cv2.INTER_CUBIC)
        H, W = blank.shape

        grid = build_grid(blank)
        ncell = sum(len(r["cells"]) for r in grid["rows"])
        print(f"  page{pi}: 枠を検出（行 {len(grid['rows'])} / セル {ncell}）")

        heat = np.zeros((H, W), np.float32)
        if files:
            heat, used = build_heatmap(page, blank, files, dpi)
            print(f"          記入済み {used} 枚でインク分布を確認")

        # マスター側の枠も検出し、行同士を対応付ける
        mblank_path = os.path.join(ROOT, "templates", "blanks",
                                   mpage.get("blank") or mpage["ref"])
        mblank = cv2.imread(mblank_path, cv2.IMREAD_GRAYSCALE)
        if mblank is None:
            print("    ! マスターの白紙様式が見つかりません")
            continue
        mgrid = build_grid(mblank)
        mrows = row_signature(mgrid, mpage)
        srows = row_signature(grid, page)
        pairs = align_rows(mrows, srows)
        matched_box_rows = sum(1 for i, j in pairs if mrows[i]["nbox"] > 0)
        print(f"          行の対応 {len(pairs)} 組"
              f"（うちチェックボックスを含む行 {matched_box_rows} 組）")
        row_of = {i: srows[j] for i, j in pairs}

        by_field = {t["field"]: t for t in page["texts"]}
        mH_px = mblank.shape[0]

        # 1) マスターの欄が入っている行を求め、対応する行へ移す
        placed = []
        for mt in mpage["texts"]:
            t = by_field.get(mt["field"])
            if t is None:
                continue
            x, y, w, h = mt["rect"]
            cy = (y + h / 2) * mH_px
            mi = None
            for i, r in enumerate(mrows):
                if r["top"] <= cy <= r["bottom"]:
                    mi = i
                    break
            target = row_of.get(mi) if mi is not None else None
            if target is None:
                t["placement"] = "推定"
                t["note"] = "対応する行が見つかりません"
                stats["failed"] += 1
                continue
            top, bottom = target["top"], target["bottom"]
            inset = max(2, int((bottom - top) * INSET_Y))
            # 横位置はマスターでの相対位置を初期値にする（後段でインクに合わせる）
            placed.append(dict(t=t, mt=mt, mx=x,
                               rect=(int(x * W), top + inset,
                                     int((x + w) * W), bottom - inset)))

        # 2) 同じ行に入った欄をまとめ、横位置は「実際に書かれている塊」で決める
        rows = {}
        for p_ in placed:
            rows.setdefault((p_["rect"][1], p_["rect"][3]), []).append(p_)

        for (top, bottom), items in rows.items():
            items.sort(key=lambda p_: p_["mx"])
            clusters = ink_clusters(heat, top, bottom, W) if files else []
            for i, p_ in enumerate(items):
                x0, y0, x1, y1 = p_["rect"]
                used_ink = False
                if clusters:
                    if len(clusters) == len(items):
                        cs, ce = clusters[i]
                        used_ink = True
                    else:
                        # 個数が合わないときは、枠内で最も重なる塊を選ぶ
                        best, bov = None, 0
                        for (cs_, ce_) in clusters:
                            ov = min(x1, ce_) - max(x0, cs_)
                            if ov > bov:
                                best, bov = (cs_, ce_), ov
                        if best and bov > (x1 - x0) * 0.15:
                            cs, ce = best
                            used_ink = True
                    if used_ink:
                        pad = max(4, int(W * 0.004))
                        x0, x1 = max(0, cs - pad), min(W, ce + pad)
                p_["t"]["rect"] = [round(x0 / W, 6), round(y0 / H, 6),
                                   round((x1 - x0) / W, 6), round((y1 - y0) / H, 6)]
                p_["t"]["placement"] = "枠に一致" + ("・記入位置で確認済み" if used_ink else "")
                p_["t"].pop("transferred", None)
                p_["t"].pop("note", None)
                stats["snapped"] += 1
                if used_ink:
                    stats["refined"] += 1

        if preview:
            vis = cv2.cvtColor(blank, cv2.COLOR_GRAY2BGR)
            col = (np.clip(heat * 3.0, 0, 1) * 255).astype(np.uint8)
            vis[:, :, 2] = np.maximum(vis[:, :, 2], col)
            for t in page["texts"]:
                x, y, w, h = t["rect"]
                ok = str(t.get("placement", "")).startswith("枠")
                c = (0, 160, 0) if "確認済み" in str(t.get("placement", "")) else \
                    ((255, 0, 0) if ok else (0, 165, 255))
                cv2.rectangle(vis, (int(x * W), int(y * H)),
                              (int((x + w) * W), int((y + h) * H)), c, 2)
            cv2.imwrite(f"{preview}_p{pi}.png", vis)

    print(f"枠に一致 {stats['snapped']} 個"
          f"（うち記入位置で確認 {stats['refined']} 個） / 推定のまま {stats['failed']} 個")
    if apply_changes:
        json.dump(tpl, open(tpl_path, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print(f"更新しました: {tpl_path}")
    else:
        print("（書き込みなし）")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True)
    ap.add_argument("--glob", default="", help="検証用の記入済みサンプル")
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--dpi", type=int, default=200)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--preview")
    args = ap.parse_args()
    learn(args.id, args.glob, args.limit, args.dpi,
          apply_changes=not args.dry_run, preview=args.preview)


if __name__ == "__main__":
    main()
