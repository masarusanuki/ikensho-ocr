# -*- coding: utf-8 -*-
"""テキストレイヤを持たない様式のテンプレートを、複数のサンプルから自動生成する。

手順:
  1. 同一様式のサンプルを N 枚そろえ、1枚を基準に射影変換で位置合わせする。
  2. 画素ごとの高パーセンタイル値を取り「白紙の様式」を復元する。
     （記入マークは一部の用紙にしか無いので高パーセンタイルでは消える）
  3. 白紙上で四角形を検出する。全て空欄なので誤検出を切り分けやすい。
  4. 文書順に並べ、公式様式(マスター)の行構成と照合して検証する。
  5. テキスト欄はマスターとの対応点(186個)から薄板スプラインで転写する。
"""
import argparse
import glob
import json
import os
import sys

import cv2
import numpy as np
import pypdfium2 as pdfium

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import form_definition as fd  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOX_SIZE_TOL = 0.15


def load_page(path, idx, dpi=200):
    doc = pdfium.PdfDocument(path)
    if idx >= len(doc):
        return None
    return np.asarray(doc[idx].render(scale=dpi / 72.0, grayscale=True).to_pil())


def align_to(src, ref):
    orb = cv2.ORB_create(4000, fastThreshold=8)
    k1, d1 = orb.detectAndCompute(cv2.GaussianBlur(src, (3, 3), 0), None)
    k2, d2 = orb.detectAndCompute(cv2.GaussianBlur(ref, (3, 3), 0), None)
    if d1 is None or d2 is None:
        return None
    bf = cv2.BFMatcher(cv2.NORM_HAMMING)
    good = [m for m, n in bf.knnMatch(d1, d2, k=2) if m.distance < 0.75 * n.distance]
    if len(good) < 12:
        return None
    sp = np.float32([k1[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    dp = np.float32([k2[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
    H, mask = cv2.findHomography(sp, dp, cv2.RANSAC, 4.0)
    if H is None or mask is None or mask.sum() < 30:
        return None
    return cv2.warpPerspective(src, H, (ref.shape[1], ref.shape[0]),
                               flags=cv2.INTER_LINEAR, borderValue=255)


def blank_form(files, page_idx, dpi=200, percentile=90):
    """位置合わせ済みスタックの高パーセンタイル合成で白紙様式を復元する。"""
    ref = load_page(files[0], page_idx, dpi)
    if ref is None:
        return None, 0
    stack = [ref]
    for f in files[1:]:
        img = load_page(f, page_idx, dpi)
        if img is None:
            continue
        w = align_to(img, ref)
        if w is not None:
            stack.append(w)
    blank = np.percentile(np.stack(stack), percentile, axis=0).astype(np.uint8)
    return blank, len(stack)


def square_candidates(gray, dpi=200):
    """四角形候補と、その枠線/内部のインク量を返す。"""
    bw = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                               cv2.THRESH_BINARY_INV, 25, 15)
    cnts, _ = cv2.findContours(bw, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    lo, hi = 0.05 * dpi, 0.22 * dpi
    out = []
    for c in cnts:
        x, y, w, h = cv2.boundingRect(c)
        if not (lo <= w <= hi and lo <= h <= hi):
            continue
        if not (0.80 <= w / h <= 1.25):
            continue
        t = max(1, int(round(min(w, h) * 0.22)))
        roi = bw[y:y + h, x:x + w] > 0
        inner = roi[t:h - t, t:w - t]
        interior = float(inner.mean()) if inner.size else 1.0
        ring_mask = np.ones_like(roi, dtype=bool)
        if inner.size:
            ring_mask[t:h - t, t:w - t] = False
        ring = float(roi[ring_mask].mean()) if ring_mask.any() else 0.0
        out.append((x, y, w, h, ring, interior))
    return out


def pick_boxes(candidates_by_page):
    """全ページ合算の最頻サイズを使って本物のチェックボックスを選ぶ。"""
    empties = [a for cands in candidates_by_page.values() for a in cands
               if a[5] < 0.16 and a[4] > 0.45]
    if not empties:
        return {p: [] for p in candidates_by_page}
    sizes = np.array([(a[2] + a[3]) / 2 for a in empties])
    bins = np.arange(sizes.min(), sizes.max() + 1.5, 1.0)
    hist, edges = np.histogram(sizes, bins=bins)
    mode = float(edges[hist.argmax()] + 0.5)
    out = {}
    for p, cands in candidates_by_page.items():
        out[p] = [a for a in cands
                  if a[5] < 0.16 and a[4] > 0.45
                  and abs((a[2] + a[3]) / 2 - mode) <= BOX_SIZE_TOL * mode]
    return out


def doc_order(boxes, row_tol=10):
    """文書順（行ごとに上→下、行内は左→右）に並べ替える。"""
    bs = sorted(boxes, key=lambda b: b[1])
    rows, cur = [], []
    for b in bs:
        if cur and b[1] - min(c[1] for c in cur) > row_tol:
            rows.append(cur)
            cur = []
        cur.append(b)
    if cur:
        rows.append(cur)
    out = []
    for r in rows:
        out.extend(sorted(r, key=lambda b: b[0]))
    return out, [len(r) for r in rows]


def master_row_shape(page_index):
    """マスターテンプレートの行構成（各行のチェックボックス数）。"""
    path = os.path.join(ROOT, "templates", "official_v1.json")
    tpl = json.load(open(path, encoding="utf-8"))
    page = next(p for p in tpl["pages"] if p["index"] == page_index)
    H = page["height"]
    bs = sorted(page["boxes"], key=lambda b: b["rect"][1])
    rows, cur = [], []
    for b in bs:
        yv = b["rect"][1] * H
        if cur and yv - min(c["rect"][1] * H for c in cur) > 10:
            rows.append(cur)
            cur = []
        cur.append(b)
    if cur:
        rows.append(cur)
    return [len(r) for r in rows]


class RowLocalMap:
    """様式間で座標を写す変換。

    意見書のような表組みでは、別様式でも「行の順序」「行内の列の順序」が保たれる一方、
    列の位置は行ごとに違う。そこで
      - y 方向: 全体を単調増加の折れ線で写す（行の順序が崩れない）
      - x 方向: 近い行の対応点だけを使って局所的に直線で写す
    という二段構えにする。薄板スプラインのような自由変形は対応点が疎な
    ヘッダ部で破綻するため使わない。
    """

    def __init__(self, src, dst, y_window=70.0, min_pts=8):
        self.src = np.asarray(src, dtype=float)
        self.dst = np.asarray(dst, dtype=float)
        self.y_window = y_window
        self.min_pts = min_pts
        self.knots_y, self.vals_y = self._fit_monotone(self.src[:, 1], self.dst[:, 1])

    @staticmethod
    def _fit_monotone(sv, dv, nbins=28):
        order = np.argsort(sv)
        sv, dv = sv[order], dv[order]
        edges = np.linspace(sv[0], sv[-1], min(nbins, max(2, len(sv) // 2)) + 1)
        xs, ys = [], []
        for i in range(len(edges) - 1):
            last = (i == len(edges) - 2)
            m = (sv >= edges[i]) & ((sv <= edges[i + 1]) if last else (sv < edges[i + 1]))
            if not m.any():
                continue
            xs.append(float(np.median(sv[m])))
            ys.append(float(np.median(dv[m])))
        if len(xs) < 2:
            xs, ys = list(sv[:2]), list(dv[:2])
        for i in range(1, len(ys)):
            ys[i] = max(ys[i], ys[i - 1] + 1e-6)
        return np.array(xs), np.array(ys)

    def _map_y(self, y):
        k, v = self.knots_y, self.vals_y
        out = np.interp(y, k, v)
        lo = (v[1] - v[0]) / max(k[1] - k[0], 1e-6)
        hi = (v[-1] - v[-2]) / max(k[-1] - k[-2], 1e-6)
        out = np.where(y < k[0], v[0] + (y - k[0]) * lo, out)
        out = np.where(y > k[-1], v[-1] + (y - k[-1]) * hi, out)
        return out

    def _map_x(self, x, y):
        """y の近くにある対応点だけで x の直線写像を作る。"""
        out = np.empty_like(x)
        for i in range(len(x)):
            win = self.y_window
            for _ in range(6):
                m = np.abs(self.src[:, 1] - y[i]) <= win
                if m.sum() >= self.min_pts and len(np.unique(self.src[m, 0])) >= 3:
                    break
                win *= 1.8
            else:
                m = np.ones(len(self.src), dtype=bool)
            sx, dx = self.src[m, 0], self.dst[m, 0]
            if len(np.unique(sx)) < 2:
                out[i] = x[i]
                continue
            a, b = np.polyfit(sx, dx, 1)
            out[i] = a * x[i] + b
        return out

    def __call__(self, pts):
        pts = np.asarray(pts, dtype=float)
        y = self._map_y(pts[:, 1])
        x = self._map_x(pts[:, 0], pts[:, 1])
        return np.stack([x, y], axis=1)


def _normalize_label(t):
    import unicodedata
    return "".join(unicodedata.normalize("NFKC", t or "").split())


def master_labels(page_index):
    """マスターPDFから、印刷されているラベルの語と位置を取り出す（正確）。"""
    import pdfplumber
    out = {}
    with pdfplumber.open(os.path.join(ROOT, "master", "主医師意見書.pdf")) as pdf:
        page = pdf.pages[page_index - 1]
        sx = page.width, page.height
        for w in page.extract_words(x_tolerance=1.5, y_tolerance=2):
            key = _normalize_label(w["text"]).replace("□", "")
            if len(key) < 2:
                continue
            out.setdefault(key, []).append(
                ((w["x0"] + w["x1"]) / 2, (w["top"] + w["bottom"]) / 2))
    # 同じ語が複数ある場合は対応が定まらないので使わない
    return {k: v[0] for k, v in out.items() if len(v) == 1}, sx


def blank_labels(blank):
    """白紙様式をOCRして、印刷されているラベルの語と位置を取り出す。"""
    try:
        from rapidocr_onnxruntime import RapidOCR
    except Exception:
        return {}
    try:
        res, _ = RapidOCR()(cv2.cvtColor(blank, cv2.COLOR_GRAY2BGR))
    except Exception:
        return {}
    out = {}
    for box, text, conf in (res or []):
        if conf < 0.6:
            continue
        key = _normalize_label(text).replace("□", "")
        if len(key) < 2:
            continue
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        out.setdefault(key, []).append((sum(xs) / 4, sum(ys) / 4))
    return {k: v[0] for k, v in out.items() if len(v) == 1}


def label_anchors(page_index, blank):
    """マスターと新様式で同じラベルの位置を突き合わせ、追加の対応点にする。

    チェックボックスが少ないヘッダ部（氏名・医療機関名など）は
    これを入れないとテキスト欄の転写精度が出ない。
    """
    mlab, (mW, mH) = master_labels(page_index)
    blab = blank_labels(blank)
    src, dst = [], []
    for key, (mx, my) in mlab.items():
        if key in blab:
            src.append([mx, my])
            dst.append(list(blab[key]))
    return src, dst, mW, mH


def transfer_texts(page_index, dst_boxes, dst_shape, blank=None):
    """マスターのテキスト欄を、チェックボックスとラベルの対応点による
単調な分離型写像で別様式へ転写する。"""
    path = os.path.join(ROOT, "templates", "official_v1.json")
    tpl = json.load(open(path, encoding="utf-8"))
    mpage = next(p for p in tpl["pages"] if p["index"] == page_index)
    mW, mH = mpage["width"], mpage["height"]
    dH, dW = dst_shape

    key = {(b["field"], b["opt"]): b["rect"] for b in mpage["boxes"]}
    src_pts, dst_pts = [], []
    for b in dst_boxes:
        r = key.get((b["field"], b["opt"]))
        if not r:
            continue
        src_pts.append([(r[0] + r[2] / 2) * mW, (r[1] + r[3] / 2) * mH])
        dst_pts.append([(b["rect"][0] + b["rect"][2] / 2) * dW,
                        (b["rect"][1] + b["rect"][3] / 2) * dH])
    n_box = len(src_pts)
    n_label = 0
    if blank is not None:
        lsrc, ldst, _, _ = label_anchors(page_index, blank)
        # 同じ位置に重ならないものだけ採用する
        for s_, d_ in zip(lsrc, ldst):
            if all(abs(s_[0] - p[0]) > 4 or abs(s_[1] - p[1]) > 4 for p in src_pts):
                src_pts.append(s_)
                dst_pts.append(d_)
                n_label += 1
    if len(src_pts) < 8:
        return []
    print(f"    対応点: チェックボックス {n_box} 個 + ラベル {n_label} 個")

    tps = RowLocalMap(src_pts, dst_pts)
    def clamp(v, lo=0.0, hi=1.0):
        return max(lo, min(hi, v))

    texts = []
    for t in mpage["texts"]:
        x, y, w, h = t["rect"]
        corners = [[x * mW, y * mH], [(x + w) * mW, y * mH],
                   [(x + w) * mW, (y + h) * mH], [x * mW, (y + h) * mH]]
        moved = tps(corners)
        x0n = clamp(float(moved[:, 0].min() / dW))
        y0n = clamp(float(moved[:, 1].min() / dH))
        x1n = clamp(float(moved[:, 0].max() / dW))
        y1n = clamp(float(moved[:, 1].max() / dH))
        if x1n - x0n < 0.005 or y1n - y0n < 0.003:
            continue        # 潰れた矩形は転写できていないので出さない
        texts.append(dict(field=t["field"], type=t["type"],
                          rect=[round(x0n, 6), round(y0n, 6),
                                round(x1n - x0n, 6), round(y1n - y0n, 6)],
                          options=t.get("options"),
                          charset=t.get("charset", ""), pii=t.get("pii", ""),
                          kind=t.get("kind", ""), era_field=t.get("era_field", ""),
                          default_era=t.get("default_era", ""),
                          # 別様式から機械的に写した暫定位置。管理画面で調整する前提。
                          transferred=True))
    return texts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--glob", required=True, help="同一様式のサンプルPDFのglobパターン")
    ap.add_argument("--id", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--dpi", type=int, default=200)
    ap.add_argument("--percentile", type=int, default=90)
    args = ap.parse_args()

    files = sorted(glob.glob(args.glob))[: args.limit]
    if not files:
        sys.exit(f"サンプルが見つかりません: {args.glob}")
    print(f"サンプル {len(files)} 件から様式 '{args.id}' を生成します")

    ref_dir = os.path.join(ROOT, "templates", "refs")
    os.makedirs(ref_dir, exist_ok=True)

    blanks, cands = {}, {}
    for pi in (1, 2):
        blank, used = blank_form(files, pi - 1, args.dpi, args.percentile)
        if blank is None:
            sys.exit(f"page{pi} を読み込めません")
        blanks[pi] = blank
        cands[pi] = square_candidates(blank, args.dpi)
        print(f"  page{pi}: {used} 枚を合成 / 四角形候補 {len(cands[pi])}")

    picked = pick_boxes(cands)
    pages_out, ok = [], True
    for pi in (1, 2):
        ordered, shape = doc_order(picked[pi])
        expect = len(fd.BOX_ORDER[pi])
        mshape = master_row_shape(pi)
        print(f"  page{pi}: チェックボックス {len(ordered)} 個 (期待 {expect})")
        if len(ordered) != expect:
            ok = False
            print(f"    ! 個数不一致 — 行構成 検出={shape}")
            print(f"                  マスター={mshape}")
            for i, (a, b) in enumerate(zip(shape, mshape)):
                if a != b:
                    print(f"    ! 行{i}: 検出{a} 個 / マスター{b} 個")
                    break
        elif shape != mshape:
            print(f"    ! 個数は一致するが行構成が異なります 検出={shape}")

        blank = blanks[pi]
        H, W = blank.shape
        page_boxes = []
        for b, (fid, oi) in zip(ordered, fd.BOX_ORDER[pi]):
            x, y, w, h = b[0], b[1], b[2], b[3]
            page_boxes.append(dict(field=fid, opt=oi,
                                   rect=[round(x / W, 6), round(y / H, 6),
                                         round(w / W, 6), round(h / H, 6)]))
        texts = transfer_texts(pi, page_boxes, (H, W), blank)
        print(f"  page{pi}: テキスト欄 {len(texts)} 個をマスターから転写")

        ref_name = f"{args.id}_p{pi}.png"
        cv2.imwrite(os.path.join(ref_dir, ref_name),
                    cv2.resize(blank, (W // 2, H // 2), interpolation=cv2.INTER_AREA))
        blank_dir = os.path.join(ROOT, "templates", "blanks")
        os.makedirs(blank_dir, exist_ok=True)
        cv2.imwrite(os.path.join(blank_dir, ref_name), blank)
        pages_out.append(dict(index=pi, width=W, height=H, ref=ref_name,
                              blank=ref_name, boxes=page_boxes, texts=texts))

    out = os.path.join(ROOT, "templates", f"{args.id}.json")
    json.dump(dict(id=args.id, name=args.name, schema_version="1.0.0",
                   page_count=2,
                   aspect=round(pages_out[0]["width"] / pages_out[0]["height"], 6),
                   generated_from="consensus", pages=pages_out),
              open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(("完了: " if ok else "要確認あり: ") + out)


if __name__ == "__main__":
    main()
