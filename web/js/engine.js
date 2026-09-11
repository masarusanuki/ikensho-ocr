/**
 * 主治医意見書 読み取りエンジン（ブラウザ版）
 *
 * 設計方針
 *  - 読み取りの大半はチェックボックス判定で行う。OCR を使わないため
 *    手書き・印刷・スキャンのいずれでも安定する。
 *  - OCR は氏名・病名などのテキスト欄に限定し、辞書で補正する。
 *  - すべて端末内で処理する。患者情報は外部に送信されない。
 */
(function (global) {
  'use strict';

  const TARGET_WIDTH = 1654;   // A4 200dpi 相当

  // 管理画面から調整できるしきい値
  const thresholds = {
    CONF_HIGH: 0.80,    // 確信度「高」の下限
    CONF_MID: 0.50,     // 確信度「中」の下限
    EMPTY_MAX: 0.10,        // 枠内インク率がこれ未満なら未チェック
    FILLED_MIN: 0.28,       // 枠内インク率がこれ以上ならチェック済み
    MARK_EMPTY_MAX: 0.012,  // 参考値 mark の目安（判定には使わない）
    MARK_FILLED_MIN: 0.030,
    INK_EMPTY_MAX: 0.02,    // 枠の中の書き込みがこれ未満なら未記入（境界 0.04）
    INK_FILLED_MIN: 0.06,
    RING_EMPTY_MAX: 0.10,   // 枠の外周の書き込み＝丸囲み（境界 0.20）
    RING_FILLED_MIN: 0.30,
    RING_BIAS_MAX: 0.50,    // 外周のインクが片側に寄っていたら隣の字とみなす
    OUT_EMPTY_MAX: 0.015,   // 枠の右下へのはみ出し（境界 0.03）
    OUT_FILLED_MIN: 0.045,
    OUT_EDGE_EMPTY_MAX: 0.010,  // 枠の右端とつながっているか（境界 0.02）
    OUT_EDGE_FILLED_MIN: 0.030,
    MIN_INLIERS: 25,        // 様式判定に必要な対応点数
  };
  function setThresholds(obj) { Object.assign(thresholds, obj || {}); }

  function confidenceLevel(c) {
    if (c >= thresholds.CONF_HIGH) return 'high';
    if (c >= thresholds.CONF_MID) return 'medium';
    return 'low';
  }

  // ---------------------------------------------------------------- utils
  function waitFor(test, timeoutMs, label) {
    return new Promise((resolve, reject) => {
      const t0 = Date.now();
      (function tick() {
        if (test()) return resolve();
        if (Date.now() - t0 > timeoutMs) return reject(new Error(label + ' の読み込みに失敗しました'));
        setTimeout(tick, 60);
      })();
    });
  }

  function canvasToGrayMat(canvas) {
    const src = cv.imread(canvas);
    const gray = new cv.Mat();
    cv.cvtColor(src, gray, cv.COLOR_RGBA2GRAY);
    src.delete();
    return gray;
  }

  function matToCanvas(mat) {
    const c = document.createElement('canvas');
    c.width = mat.cols; c.height = mat.rows;
    cv.imshow(c, mat);
    return c;
  }

  // ------------------------------------------------------------ 前処理
  /** 撮影写真の照明ムラを平坦化する（スキャン画像でも無害）。 */
  function flattenIllumination(gray) {
    const small = new cv.Mat();
    const k = 8;
    cv.resize(gray, small, new cv.Size(Math.max(1, Math.round(gray.cols / k)),
                                       Math.max(1, Math.round(gray.rows / k))), 0, 0, cv.INTER_AREA);
    const blurred = new cv.Mat();
    cv.medianBlur(small, blurred, 21);
    const bg = new cv.Mat();
    cv.resize(blurred, bg, new cv.Size(gray.cols, gray.rows), 0, 0, cv.INTER_LINEAR);
    const out = new cv.Mat();
    // out = gray / bg * 220
    const grayF = new cv.Mat(); const bgF = new cv.Mat();
    gray.convertTo(grayF, cv.CV_32F);
    bg.convertTo(bgF, cv.CV_32F);
    cv.max(bgF, new cv.Mat(bgF.rows, bgF.cols, cv.CV_32F, new cv.Scalar(1)), bgF);
    const div = new cv.Mat();
    cv.divide(grayF, bgF, div, 220.0);
    div.convertTo(out, cv.CV_8U);
    small.delete(); blurred.delete(); bg.delete(); grayF.delete(); bgF.delete(); div.delete();
    return out;
  }

  /** 写真から用紙の四隅を検出して台形補正する。見つからなければ null。 */
  function dewarpPaper(gray) {
    const scale = 1000 / gray.cols;
    const small = new cv.Mat();
    cv.resize(gray, small, new cv.Size(1000, Math.round(gray.rows * scale)), 0, 0, cv.INTER_AREA);
    const blur = new cv.Mat(); cv.GaussianBlur(small, blur, new cv.Size(5, 5), 0);
    const edges = new cv.Mat(); cv.Canny(blur, edges, 40, 120);
    const kernel = cv.getStructuringElement(cv.MORPH_RECT, new cv.Size(3, 3));
    cv.dilate(edges, edges, kernel);
    const contours = new cv.MatVector(); const hier = new cv.Mat();
    cv.findContours(edges, contours, hier, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE);
    let best = null, bestArea = 0.35 * small.cols * small.rows;
    for (let i = 0; i < contours.size(); i++) {
      const c = contours.get(i);
      const peri = cv.arcLength(c, true);
      const approx = new cv.Mat();
      cv.approxPolyDP(c, approx, 0.02 * peri, true);
      if (approx.rows === 4 && cv.isContourConvex(approx)) {
        const area = Math.abs(cv.contourArea(approx));
        if (area > bestArea) {
          if (best) best.delete();
          best = approx.clone(); bestArea = area;
        }
      }
      approx.delete(); c.delete();
    }
    contours.delete(); hier.delete(); edges.delete(); blur.delete(); kernel.delete();

    if (!best) { small.delete(); return null; }
    const pts = [];
    for (let i = 0; i < 4; i++) pts.push([best.data32S[i * 2] / scale, best.data32S[i * 2 + 1] / scale]);
    best.delete(); small.delete();

    // 左上→右上→右下→左下 に並べる
    const bySum = [...pts].sort((a, b) => (a[0] + a[1]) - (b[0] + b[1]));
    const byDiff = [...pts].sort((a, b) => (a[0] - a[1]) - (b[0] - b[1]));
    const tl = bySum[0], br = bySum[3], bl = byDiff[0], tr = byDiff[3];
    const dist = (p, q) => Math.hypot(p[0] - q[0], p[1] - q[1]);
    let w = Math.max(dist(br, bl), dist(tr, tl));
    let h = Math.max(dist(tr, br), dist(tl, bl));
    const a4 = 297 / 210;
    if (h / w < a4 * 0.8 || h / w > a4 * 1.2) h = w * a4;
    const outW = Math.round(w), outH = Math.round(h);
    const srcTri = cv.matFromArray(4, 1, cv.CV_32FC2, [tl[0], tl[1], tr[0], tr[1], br[0], br[1], bl[0], bl[1]]);
    const dstTri = cv.matFromArray(4, 1, cv.CV_32FC2, [0, 0, outW - 1, 0, outW - 1, outH - 1, 0, outH - 1]);
    const M = cv.getPerspectiveTransform(srcTri, dstTri);
    const out = new cv.Mat();
    cv.warpPerspective(gray, out, M, new cv.Size(outW, outH), cv.INTER_CUBIC,
                       cv.BORDER_CONSTANT, new cv.Scalar(255));
    srcTri.delete(); dstTri.delete(); M.delete();
    return out;
  }

  // ------------------------------------------------------------ 位置合わせ
  function registerToRef(srcGray, refGray, nfeat = 4000) {
    // OpenCV.js は ORB のフル引数コンストラクタを公開していないため、
    // 既定で生成してからセッターで調整する。
    const orb = new cv.ORB();
    orb.setMaxFeatures(nfeat);
    orb.setScaleFactor(1.2);
    orb.setNLevels(8);
    orb.setFastThreshold(8);   // スキャン画像でも特徴点が取れるよう下げる
    const k1 = new cv.KeyPointVector(), d1 = new cv.Mat();
    const k2 = new cv.KeyPointVector(), d2 = new cv.Mat();
    const s1 = new cv.Mat(), s2 = new cv.Mat();
    cv.GaussianBlur(srcGray, s1, new cv.Size(3, 3), 0);
    cv.GaussianBlur(refGray, s2, new cv.Size(3, 3), 0);
    orb.detectAndCompute(s1, new cv.Mat(), k1, d1);
    orb.detectAndCompute(s2, new cv.Mat(), k2, d2);
    let result = { H: null, matches: 0, inliers: 0 };
    if (d1.rows >= 12 && d2.rows >= 12) {
      const bf = new cv.BFMatcher(cv.NORM_HAMMING, false);
      const knn = new cv.DMatchVectorVector();
      bf.knnMatch(d1, d2, knn, 2);
      const srcPts = [], dstPts = [];
      for (let i = 0; i < knn.size(); i++) {
        const pair = knn.get(i);
        if (pair.size() < 2) { pair.delete(); continue; }
        const m = pair.get(0), n = pair.get(1);
        if (m.distance < 0.75 * n.distance) {
          const p = k1.get(m.queryIdx).pt, q = k2.get(m.trainIdx).pt;
          srcPts.push(p.x, p.y); dstPts.push(q.x, q.y);
        }
        pair.delete();
      }
      const nGood = srcPts.length / 2;
      if (nGood >= 12) {
        const sMat = cv.matFromArray(nGood, 1, cv.CV_32FC2, srcPts);
        const dMat = cv.matFromArray(nGood, 1, cv.CV_32FC2, dstPts);
        const mask = new cv.Mat();
        const H = cv.findHomography(sMat, dMat, cv.RANSAC, 4.0, mask);
        let inl = 0;
        for (let i = 0; i < mask.rows; i++) if (mask.data[i]) inl++;
        if (!H.empty()) result = { H: H.clone(), matches: nGood, inliers: inl };
        H.delete(); mask.delete(); sMat.delete(); dMat.delete();
      }
      knn.delete(); bf.delete();
    }
    orb.delete(); k1.delete(); k2.delete(); d1.delete(); d2.delete(); s1.delete(); s2.delete();
    return result;
  }

  function matchScore(inliers, matches) {
    if (!matches) return 0;
    return Math.round((inliers / matches * 0.6 + Math.min(inliers / 120, 1) * 0.4) * 10000) / 10000;
  }

  // ------------------------------------------------------------ チェック判定
  function binarize(gray) {
    const bw = new cv.Mat();
    cv.adaptiveThreshold(gray, bw, 255, cv.ADAPTIVE_THRESH_MEAN_C, cv.THRESH_BINARY_INV, 31, 12);
    return bw;
  }

  function fillRatio(bw, x, y, w, h) {
    let t = Math.max(1, Math.round(Math.min(w, h) * 0.26));
    if (w - 2 * t <= 1 || h - 2 * t <= 1) t = Math.max(1, Math.floor(Math.min(w, h) / 4));
    const x0 = x + t, y0 = y + t, ww = w - 2 * t, hh = h - 2 * t;
    if (ww <= 0 || hh <= 0) return 0;
    const roi = bw.roi(new cv.Rect(x0, y0, ww, hh));
    const n = cv.countNonZero(roi);
    roi.delete();
    return n / (ww * hh);
  }


  const MARK_MARGIN = 0.45;   // 枠の外周（丸囲み）を見る窓の広さ
  const BLANK_DILATE = 5;      // 枠の判定で白紙側を太らせる幅（重ね合わせのずれ）
  // **文字欄では 3 を使う。** 枠の判定では印刷の枠線を確実に消したいので 5 だが、
  // 同じ値を文字欄に使うと罫線やラベルに重なった手書きまで消え、
  // 「書き込みが無い」と誤判定して欄をまるごと空にしてしまう（実際にそうなった）
  const TEXT_BLANK_DILATE = 3;
  // 二重線で消した印
  const STRIKE_BANDS_MIN = 1;      // 枠を左右に突き抜ける長い横線の本数
  const STRIKE_ALL_BANDS_MIN = 2;  // 突き抜けを問わない本数（二重線なので2本）
  const STRIKE_LEN_MIN = 1.8;      // 同じ項目に他の印があるときの線の長さ（枠幅比）
  const STRIKE_LEN_ALONE = 2.2;    // ないとき
  const STRIKE_SIDE = 0.3;         // 枠の左右どこまで出ていれば「突き抜けた」か

  /**
   * 白紙様式との差分をとり、手書きのマークだけを残した2値画像を作る。
   * 枠線・ラベル・説明文が消えるので、枠からはみ出したレ点や丸印も拾える。
   *
   * `dilate` は白紙側のインクを太らせる幅。**用途によって変える。**
   * 枠の判定は 5（印刷の枠線を確実に消す）、文字欄は 3
   * （太らせすぎると罫線に重なった手書きまで消える）。
   */
  function markLayer(warped, blank, dilate) {
    if (!blank || blank.cols !== warped.cols || blank.rows !== warped.rows) return null;
    const d = Math.max(1, Math.round(dilate || BLANK_DILATE));
    const scan = binarize(warped);
    const base = binarize(blank);
    const k = cv.getStructuringElement(cv.MORPH_RECT, new cv.Size(d, d));
    cv.dilate(base, base, k);                   // 位置ずれの許容
    const inv = new cv.Mat();
    cv.bitwise_not(base, inv);
    const diff = new cv.Mat();
    cv.bitwise_and(scan, inv, diff);
    const k2 = cv.getStructuringElement(cv.MORPH_RECT, new cv.Size(2, 2));
    cv.morphologyEx(diff, diff, cv.MORPH_OPEN, k2);   // 孤立ノイズの除去
    scan.delete(); base.delete(); inv.delete(); k.delete(); k2.delete();
    return diff;
  }

  function markRatio(diff, x, y, w, h) {
    const mx = Math.round(w * MARK_MARGIN), my = Math.round(h * MARK_MARGIN);
    const x0 = Math.max(0, x - mx), y0 = Math.max(0, y - my);
    const x1 = Math.min(diff.cols, x + w + mx), y1 = Math.min(diff.rows, y + h + my);
    if (x1 - x0 < 2 || y1 - y0 < 2) return 0;
    const roi = diff.roi(new cv.Rect(x0, y0, x1 - x0, y1 - y0));
    const r = cv.countNonZero(roi) / (roi.rows * roi.cols);
    roi.delete();
    return r;
  }

  /** 枠の中だけの書き込み量。隣の手書きを拾わない。 */
  function inkRatio(diff, x, y, w, h) {
    const x0 = Math.max(0, x), y0 = Math.max(0, y);
    const x1 = Math.min(diff.cols, x + w), y1 = Math.min(diff.rows, y + h);
    if (x1 - x0 < 1 || y1 - y0 < 1) return 0;
    const roi = diff.roi(new cv.Rect(x0, y0, x1 - x0, y1 - y0));
    const r = cv.countNonZero(roi) / (roi.rows * roi.cols);
    roi.delete();
    return r;
  }

  /**
   * 枠の外周の書き込み量と、その左右の偏り。
   * 丸囲みは外周がぐるりと濃くなる。隣の字なら片側に偏る。
   */
  function ringRatio(diff, x, y, w, h) {
    const mx = Math.round(w * MARK_MARGIN), my = Math.round(h * MARK_MARGIN);
    const rx0 = Math.max(0, x - mx), ry0 = Math.max(0, y - my);
    const rx1 = Math.min(diff.cols, x + w + mx), ry1 = Math.min(diff.rows, y + h + my);
    if (rx1 - rx0 < 2 || ry1 - ry0 < 2) return [0, 0];
    const win = diff.roi(new cv.Rect(rx0, ry0, rx1 - rx0, ry1 - ry0));
    const ix0 = Math.max(0, x), iy0 = Math.max(0, y);
    const ix1 = Math.min(diff.cols, x + w), iy1 = Math.min(diff.rows, y + h);
    const hasInner = ix1 - ix0 > 0 && iy1 - iy0 > 0;
    const inner = hasInner ? diff.roi(new cv.Rect(ix0, iy0, ix1 - ix0, iy1 - iy0)) : null;
    const total = cv.countNonZero(win);
    const innerN = inner ? cv.countNonZero(inner) : 0;
    const innerArea = inner ? inner.rows * inner.cols : 0;
    const area = Math.max(1, win.rows * win.cols - innerArea);
    const cx = Math.max(1, Math.trunc(x + w / 2 - rx0));
    const lw = Math.min(cx, win.cols);
    const leftRoi = win.roi(new cv.Rect(0, 0, lw, win.rows));
    const left = cv.countNonZero(leftRoi);
    leftRoi.delete();
    const bias = Math.abs(left - (total - left)) / Math.max(total, 1);
    win.delete();
    if (inner) inner.delete();
    return [Math.max(0, total - innerN) / area, bias];
  }

  /**
   * 枠の右下にずれて書かれた印を拾う。
   * はみ出した印は枠の右端に掛かったまま外へ伸びる。
   * 隣の手書きは枠に触れないので、枠の右端の濃さも併せて見る。
   */
  function outsideRatio(diff, x, y, w, h) {
    const qx0 = Math.max(0, x + Math.trunc(w * 0.35));
    const qy0 = Math.max(0, y - Math.trunc(h * 0.1));
    const qx1 = Math.min(diff.cols, x + Math.trunc(w * 1.6));
    const qy1 = Math.min(diff.rows, y + Math.trunc(h * 1.4));
    let out = 0;
    if (qx1 - qx0 > 0 && qy1 - qy0 > 0) {
      const q = diff.roi(new cv.Rect(qx0, qy0, qx1 - qx0, qy1 - qy0));
      out = cv.countNonZero(q) / (q.rows * q.cols);
      q.delete();
    }
    const tx0 = Math.max(0, x + Math.trunc(w * 0.6)), tx1 = Math.min(diff.cols, x + w);
    const ty0 = Math.max(0, y), ty1 = Math.min(diff.rows, y + h);
    let edge = 0;
    if (tx1 - tx0 > 0 && ty1 - ty0 > 0) {
      const t = diff.roi(new cv.Rect(tx0, ty0, tx1 - tx0, ty1 - ty0));
      edge = cv.countNonZero(t) / (t.rows * t.cols);
      t.delete();
    }
    return [out, edge];
  }

  /** 各行のインク数を配列で返す。 */
  function rowCounts(mat) {
    const dst = new cv.Mat();
    cv.reduce(mat, dst, 1, cv.REDUCE_SUM, cv.CV_32S);
    const a = new Int32Array(dst.rows);
    for (let i = 0; i < dst.rows; i++) a[i] = dst.intAt(i, 0) / 255;
    dst.delete();
    return a;
  }

  /** しきい値を超える行のかたまりの数。 */
  function countBands(rows, need) {
    let bands = 0, prev = false;
    for (const v of rows) {
      const on = v >= need;
      if (on && !prev) bands++;
      prev = on;
    }
    return bands;
  }

  /**
   * 枠を横切る「手書きの長い横線」の長さと本数。二重線で消した印を見つける。
   * 差分では線が枠線や文字と重なった部分で途切れるので、元画像から横線だけを
   * 取り出し、白紙様式にも同じ線があるもの（罫線）を引いて求める。
   */
  function strikeLines(bw, blankBw, x, y, w, h) {
    if (!blankBw) return [0, 0, 0];
    const by0 = Math.max(0, y - h), by1 = Math.min(bw.rows, y + h * 2);
    const bx0 = Math.max(0, x - Math.trunc(w * 1.8));
    const bx1 = Math.min(bw.cols, x + Math.trunc(w * 2.8));
    if (bx1 - bx0 < 4 || by1 - by0 < 3) return [0, 0, 0];
    const rect = new cv.Rect(bx0, by0, bx1 - bx0, by1 - by0);
    const band = bw.roi(rect), bband = blankBw.roi(rect);
    const ker = cv.getStructuringElement(cv.MORPH_RECT,
                                         new cv.Size(Math.max(6, Math.trunc(w * 1.3)), 1));
    const lines = new cv.Mat(), plines = new cv.Mat(), inv = new cv.Mat(),
          written = new cv.Mat();
    cv.morphologyEx(band, lines, cv.MORPH_OPEN, ker);
    cv.morphologyEx(bband, plines, cv.MORPH_OPEN, ker);
    // 罫線は重ね合わせのずれで数ピクセル動く。縦に厚く膨らませて確実に消す
    const dk = cv.getStructuringElement(cv.MORPH_RECT, new cv.Size(5, 9));
    cv.dilate(plines, plines, dk);
    cv.bitwise_not(plines, inv);
    cv.bitwise_and(lines, inv, written);
    const ry0 = Math.max(0, y - by0 + Math.trunc(h * 0.12));
    const ry1 = Math.min(written.rows, y - by0 + h - Math.trunc(h * 0.12));
    let result = [0, 0, 0];
    if (ry1 - ry0 > 0) {
      const seg = written.roi(new cv.Rect(0, ry0, written.cols, ry1 - ry0));
      const rows = rowCounts(seg);
      const need = w * 1.2;
      const bandsAll = countBands(rows, need);
      // 枠の左右どちらにも突き抜けている行だけに絞る
      const lx = Math.max(1, x - bx0 - Math.trunc(w * STRIKE_SIDE));
      const rx = Math.min(seg.cols - 1, x - bx0 + w + Math.trunc(w * STRIKE_SIDE));
      const lRoi = seg.roi(new cv.Rect(0, 0, Math.min(lx, seg.cols), seg.rows));
      const rRoi = seg.roi(new cv.Rect(rx, 0, Math.max(1, seg.cols - rx), seg.rows));
      const lr = rowCounts(lRoi), rr = rowCounts(rRoi);
      lRoi.delete(); rRoi.delete();
      let maxRow = 0;
      const kept = new Int32Array(rows.length);
      for (let i = 0; i < rows.length; i++) {
        kept[i] = (lr[i] > 0 && rr[i] > 0) ? rows[i] : 0;
        if (kept[i] > maxRow) maxRow = kept[i];
      }
      result = [maxRow / Math.max(w, 1), countBands(kept, need), bandsAll];
      seg.delete();
    }
    band.delete(); bband.delete(); ker.delete(); dk.delete();
    lines.delete(); plines.delete(); inv.delete(); written.delete();
    return result;
  }

  /**
   * 二重線で消された印を未チェックに戻す。
   * 同じ項目に他の印があるとき（＝書き直し）は、より緩く見る。
   */
  function resolveStrikes(rs) {
    const byField = {};
    for (const r of rs) (byField[r.field] = byField[r.field] || []).push(r);
    for (const group of Object.values(byField)) {
      for (const r of group) {
        if (!r.checked || (r.strikeBands || 0) < STRIKE_BANDS_MIN ||
            (r.strikeAll || 0) < STRIKE_ALL_BANDS_MIN) continue;
        const others = group.filter(o => o !== r && o.checked).length;
        const need = others ? STRIKE_LEN_MIN : STRIKE_LEN_ALONE;
        if ((r.strikeLen || 0) >= need) {
          r.struck = true;
          r.checked = false;
          r.score = Math.min(r.score, 0.45);
          r.confidence = scoreConfidence(r.score);
        }
      }
    }
  }

  function unit(v, lo, hi) {
    if (hi <= lo) return 0;
    return Math.max(0, Math.min(1, (v - lo) / (hi - lo)));
  }

  /**
   * 記入の強さを 0..1 で表す。0.5 以上を「印あり」とする。
   * 書き方によって印の現れる場所が違うので、一番強い見方を採る。
   *   枠の中に収まった印 → fill / ink
   *   枠を丸で囲んだ印   → ring（左右に偏っていたら隣の字とみなす）
   *   枠外にはみ出した印 → out（枠の右端とつながっているものだけ）
   */
  function combinedScore(fill, ink, ring, ringBias, outMark, outEdge, hasDiff) {
    const t = thresholds;
    let s = unit(fill, t.EMPTY_MAX, t.FILLED_MIN);
    if (hasDiff) {
      s = Math.max(s, unit(ink, t.INK_EMPTY_MAX, t.INK_FILLED_MIN));
      if (ringBias <= t.RING_BIAS_MAX) {
        s = Math.max(s, unit(ring, t.RING_EMPTY_MAX, t.RING_FILLED_MIN));
      }
      s = Math.max(s, Math.min(unit(outMark, t.OUT_EMPTY_MAX, t.OUT_FILLED_MIN),
                               unit(outEdge, t.OUT_EDGE_EMPTY_MAX, t.OUT_EDGE_FILLED_MIN)));
    }
    return s;
  }

  const scoreConfidence = s => Math.min(1, 0.45 + Math.abs(s - 0.5) * 1.10);

  /** 枠のすぐ外側のインク率。枠を丸で囲む記入を拾うために使う。 */
  function haloRatio(bw, x, y, w, h) {
    const mx = Math.round(w * 0.55), my = Math.round(h * 0.55);
    const x0 = Math.max(0, x - mx), y0 = Math.max(0, y - my);
    const x1 = Math.min(bw.cols, x + w + mx), y1 = Math.min(bw.rows, y + h + my);
    if (x1 - x0 < 2 || y1 - y0 < 2) return 0;
    const outer = bw.roi(new cv.Rect(x0, y0, x1 - x0, y1 - y0));
    const inner = bw.roi(new cv.Rect(x, y, w, h));
    const total = cv.countNonZero(outer) - cv.countNonZero(inner);
    const area = (x1 - x0) * (y1 - y0) - w * h;
    outer.delete(); inner.delete();
    return area > 0 ? Math.max(0, total) / area : 0;
  }

  /**
   * 枠を丸で囲む記入を検出する。
   * 枠の内側が薄くても、同じ項目の他の選択肢より枠の外周が明らかに濃ければ
   * 「丸で囲まれた」とみなす。ラベル文字は全選択肢に等しく乗るので、
   * 中央値との差を見ることで文字の影響を打ち消せる。
   */
  function detectCircled(rs) {
    if (rs.length < 2) return;
    if (rs.some(r => r.checked)) return;
    const halos = rs.map(r => r.halo || 0).sort((a, b) => a - b);
    const base = halos[Math.floor(halos.length / 2)];
    const best = rs.reduce((a, b) => ((b.halo || 0) > (a.halo || 0) ? b : a));
    const others = rs.filter(r => r !== best).map(r => r.halo || 0).sort((a, b) => b - a);
    const runnerUp = others[0] || 0;
    const HALO_EXCESS_MIN = 0.06;
    if ((best.halo || 0) - base < HALO_EXCESS_MIN ||
        (best.halo || 0) - runnerUp < HALO_EXCESS_MIN / 2) return;
    const excess = (best.halo || 0) - Math.max(base, runnerUp);
    best.circled = true;
    best.checked = true;
    best.confidence = Math.min(0.85, 0.40 + excess / 0.12 * 0.45);
    best.score = Math.max(best.score, 0.55);
  }

  function readBoxes(warped, boxes, blank) {
    const bw = binarize(warped);
    const diff = markLayer(warped, blank);
    const blankBw = (blank && blank.cols === warped.cols && blank.rows === warped.rows)
      ? binarize(blank) : null;
    const W = warped.cols, H = warped.rows;
    const out = [];
    for (const b of boxes) {
      const [rx, ry, rw, rh] = b.rect;
      let x = Math.round(rx * W), y = Math.round(ry * H);
      const w = Math.max(3, Math.round(rw * W)), h = Math.max(3, Math.round(rh * H));
      x = Math.max(0, Math.min(x, W - w)); y = Math.max(0, Math.min(y, H - h));
      const fill = fillRatio(bw, x, y, w, h);
      const mark = diff ? markRatio(diff, x, y, w, h) : 0;
      const ink = diff ? inkRatio(diff, x, y, w, h) : 0;
      const [ring, ringBias] = diff ? ringRatio(diff, x, y, w, h) : [0, 0];
      const [outMark, outEdge] = diff ? outsideRatio(diff, x, y, w, h) : [0, 0];
      const [strikeLen, strikeBands, strikeAll] = strikeLines(bw, blankBw, x, y, w, h);
      const halo = haloRatio(bw, x, y, w, h);
      const score = combinedScore(fill, ink, ring, ringBias, outMark, outEdge, !!diff);
      out.push({ field: b.field, opt: b.opt, fill, mark, ink, ring, ringBias,
                 outMark, outEdge, strikeLen, strikeBands, strikeAll, halo, score,
                 rect: b.rect, circled: false, struck: false, checked: score >= 0.5,
                 confidence: scoreConfidence(score) });
    }
    bw.delete();
    if (diff) diff.delete();
    if (blankBw) blankBw.delete();
    resolveStrikes(out);
    return out;
  }

  function resolveGroups(readings, schema) {
    const grouped = {};
    for (const r of readings) (grouped[r.field] = grouped[r.field] || []).push(r);
    const result = {};
    for (const [fid, rs] of Object.entries(grouped)) {
      const f = schema.byId[fid];
      if (!f) continue;
      rs.sort((a, b) => a.opt - b.opt);
      detectCircled(rs);
      const detail = rs.map(r => ({ opt: r.opt, fill: +r.fill.toFixed(4),
                                    halo: +(r.halo || 0).toFixed(4), circled: !!r.circled,
                                    mark: +(r.mark || 0).toFixed(4),
                                    ink: +(r.ink || 0).toFixed(4), struck: !!r.struck,
                                    score: +r.score.toFixed(4), checked: r.checked }));
      if (f.type === 'flag') {
        result[fid] = { value: rs[0].checked, confidence: rs[0].confidence, detail };
        continue;
      }
      const options = f.options || [];
      if (f.type === 'choice') {
        const ranked = [...rs].sort((a, b) => b.score - a.score);
        const top = ranked[0], second = ranked[1] ? ranked[1].score : 0;
        if (!top.checked) {
          result[fid] = { value: null, confidence: top.confidence, detail };
        } else {
          const margin = top.score - second;
          result[fid] = {
            value: options[top.opt] != null ? options[top.opt] : String(top.opt),
            confidence: Math.min(top.confidence, Math.min(1, 0.35 + margin * 0.65)),
            detail
          };
        }
        continue;
      }
      const picked = rs.filter(r => r.checked)
                       .map(r => options[r.opt] != null ? options[r.opt] : String(r.opt));
      result[fid] = { value: picked, confidence: Math.min(...rs.map(r => r.confidence)), detail };
    }
    return result;
  }

  /** 「男・女」「明・大・昭」など丸で囲む方式を読む。 */
  function readCircle(warped, rect, options, alwaysPick) {
    const W = warped.cols, H = warped.rows;
    const x0 = Math.max(0, Math.round(rect[0] * W)), y0 = Math.max(0, Math.round(rect[1] * H));
    const x1 = Math.min(W, Math.round((rect[0] + rect[2]) * W));
    const y1 = Math.min(H, Math.round((rect[1] + rect[3]) * H));
    if (x1 - x0 < 6 || y1 - y0 < 6 || !options || !options.length) {
      return { value: null, confidence: 0, detail: [] };
    }
    const roi = warped.roi(new cv.Rect(x0, y0, x1 - x0, y1 - y0));
    const bw = binarize(roi);
    const n = options.length;
    const vertical = (y1 - y0) > (x1 - x0) * 1.4;
    const scores = [];
    for (let i = 0; i < n; i++) {
      let r;
      if (vertical) {
        const a = Math.round(bw.rows * i / n), b = Math.round(bw.rows * (i + 1) / n);
        r = bw.roi(new cv.Rect(0, a, bw.cols, Math.max(1, b - a)));
      } else {
        const a = Math.round(bw.cols * i / n), b = Math.round(bw.cols * (i + 1) / n);
        r = bw.roi(new cv.Rect(a, 0, Math.max(1, b - a), bw.rows));
      }
      scores.push(cv.countNonZero(r) / (r.rows * r.cols) );
      r.delete();
    }
    roi.delete(); bw.delete();
    // 中央値。要素数が偶数のときは中央2つの平均を採る。
    // Math.floor(n/2) だけだと n=2 で最大値になり、どの選択肢も
    // 「印なし」と判定されてしまう（男・女の欄がこれに当たる）。
    const sorted = [...scores].sort((a, b) => a - b);
    const mid = Math.floor(sorted.length / 2);
    const base = sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
    const excess = scores.map(s => s - base);
    const top = excess.indexOf(Math.max(...excess));
    const rank = [...excess].sort((a, b) => b - a);
    const margin = rank[0] - (rank[1] || 0);
    const detail = scores.map((s, i) => ({ opt: i, score: +s.toFixed(4) }));
    if (rank[0] <= 0.012) {
      if (!alwaysPick) return { value: null, confidence: 0.2, detail };
      // 必ず記入される欄なので、印が弱くても濃い方を採る（確信度は低くする）
      return { value: options[top], confidence: 0.25, detail, weak: true };
    }
    return { value: options[top], confidence: Math.min(1, 0.30 + margin / 0.05 * 0.70), detail };
  }

  // ------------------------------------------------ テキスト欄の切り出しと検算
  // Python 版の textbox.py / text_check.py と同じ規則。片方だけ直さないこと。
  const WIDEN_MAX_PAD = 0.030;   // 左へ広げてよい上限（ページ幅に対する割合）
  const WIDEN_GAP_RATIO = 0.35;  // 印刷内容との間に空ける余白（行の高さに対する割合）
  const WIDEN_GAP_MIN = 3;
  const WIDEN_INK_MIN = 2;

  /** 白紙様式の指定範囲について、列ごとの印刷インクの画素数を数える。 */
  function columnInk(blank, x, y, w, h) {
    // 画像の外にはみ出す指定で roi が例外を投げるため、必ず内側に収める
    x = Math.max(0, Math.min(blank.cols - 1, Math.round(x)));
    y = Math.max(0, Math.min(blank.rows - 1, Math.round(y)));
    w = Math.min(Math.round(w), blank.cols - x);
    h = Math.min(Math.round(h), blank.rows - y);
    if (!(w > 0) || !(h > 0)) return [];
    const band = blank.roi(new cv.Rect(x, y, w, h));
    const bw = binarize(band);
    const k = cv.getStructuringElement(cv.MORPH_RECT, new cv.Size(3, 3));
    cv.dilate(bw, bw, k);
    // roi は連続領域とは限らないので、写して素の配列として見る
    const flat = bw.isContinuous() ? bw : bw.clone();
    const d = flat.data, cols = flat.cols, rows = flat.rows;
    const out = new Array(cols).fill(0);
    for (let r = 0; r < rows; r++) {
      const base = r * cols;
      for (let c = 0; c < cols; c++) if (d[base + c]) out[c]++;
    }
    if (flat !== bw) flat.delete();
    band.delete(); bw.delete(); k.delete();
    return out;
  }

  /**
   * 測った左端が記入の先頭に食い込んでいることがあるので、
   * 白紙様式の印刷内容にぶつからない範囲だけ左へ広げる。
   */
  function widenLeft(blank, rect) {
    if (!blank || !rect || !rect.every(v => Number.isFinite(v))) return rect;
    const W = blank.cols, H = blank.rows;
    const x0 = Math.round(rect[0] * W);
    const y0 = Math.max(0, Math.round(rect[1] * H));
    const y1 = Math.min(H, Math.round((rect[1] + rect[3]) * H));
    // 欄が画像の外や端に掛かっている場合は触らない
    if (x0 <= 1 || x0 >= W - 1 || y1 - y0 < 4) return rect;
    const gap = Math.max(WIDEN_GAP_MIN, Math.round((y1 - y0) * WIDEN_GAP_RATIO));
    // 欄の左端のすぐ内側に印刷（「（」など）がある場合は、
    // もともと印刷の際まで測れているので広げない
    const inside = columnInk(blank, x0, y0, Math.min(W - x0, gap), y1 - y0);
    if (inside.some(n => n >= WIDEN_INK_MIN)) return rect;   // すぐ内側に印刷がある

    const limit = Math.max(0, x0 - Math.round(WIDEN_MAX_PAD * W));
    if (x0 - limit < 2) return rect;

    const col = columnInk(blank, limit, y0, x0 - limit, y1 - y0);
    let newX0 = x0;
    for (let i = col.length - 1; i >= 0; i--) {
      if (col[i] >= WIDEN_INK_MIN) break;
      newX0 = limit + i;
    }
    newX0 = Math.min(x0, newX0 + gap);
    if (newX0 >= x0) return rect;
    const nx = newX0 / W;
    return [nx, rect[1], rect[2] + (rect[0] - nx), rect[3]];
  }

  // 先頭・末尾に残りやすい記号。「→ 対処方針 （」のような印刷を拾ったときに出る。
  // 括弧は対応が取れているかどうかで扱いを変えるので別に持つ。
  // （Python の text_check.py と同じ。片方だけ直さないこと）
  // 書き込みの周りに残す余白（文字の高さに対する割合）
  const INK_MARGIN = 0.35;
  // Python 側の _r（.5 は切り上げ）と同じ丸め
  const _r = Math.round;

  /**
   * 書き込みのある範囲まで矩形を詰める（Python の textbox.ink_crop と同じ）。
   *
   * 欄には印刷された罫線・カッコ・単位（cm など）が入っている。
   * 認識モデルはそれも文字として読もうとするので、書き込みだけに寄せた方が正確。
   * 実測で 文字正解率 78.0% → 84.6%、完全一致 40.0% → 60.0%。
   */
  function inkCrop(diff, rect, margin) {
    if (!diff || !rect || !rect.every(v => Number.isFinite(v))) return rect;
    const W = diff.cols, H = diff.rows;
    const x0 = Math.max(0, _r(rect[0] * W)), y0 = Math.max(0, _r(rect[1] * H));
    const x1 = Math.min(W, _r((rect[0] + rect[2]) * W));
    const y1 = Math.min(H, _r((rect[1] + rect[3]) * H));
    if (x1 - x0 < 8 || y1 - y0 < 8) return rect;
    const roi = diff.roi(new cv.Rect(x0, y0, x1 - x0, y1 - y0));
    const win = roi.isContinuous() ? roi : roi.clone();
    const rows = win.rows, cols = win.cols, d = win.data;
    let first = -1, last = -1, top = -1, bottom = -1;
    for (let r = 0; r < rows; r++) {
      const base = r * cols;
      for (let c = 0; c < cols; c++) {
        if (d[base + c]) {
          if (top < 0) top = r;
          bottom = r;
          if (first < 0 || c < first) first = c;
          if (c > last) last = c;
        }
      }
    }
    if (win !== roi) win.delete();
    roi.delete();
    if (first < 0) return rect;
    const pad = Math.max(2, _r((bottom - top + 1) * (margin || INK_MARGIN)));
    const nx0 = Math.max(x0, x0 + first - pad);
    const nx1 = Math.min(x1, x0 + last + 1 + pad);
    const ny0 = Math.max(y0, y0 + top - pad);
    const ny1 = Math.min(y1, y0 + bottom + 1 + pad);
    if (nx1 - nx0 < 8 || ny1 - ny0 < 8) return rect;   // 詰めすぎは避ける
    return [nx0 / W, ny0 / H, (nx1 - nx0) / W, (ny1 - ny0) / H];
  }

  /**
   * 矩形の中の「書き込みのかたまり」を左から順に返す。
   *
   * 白紙様式との差分を使うので、**印刷されている文字（年・月・日・罫線）は入らない**。
   * 日付欄では、かたまりがそのまま 年・月・日 の数字になる。
   * 文字の検出モデルを積まずに、それに近いことができる。
   */
  function inkGroups(diff, rect, gapRatio) {
    const out = [];
    if (!diff || !rect || !rect.every(v => Number.isFinite(v))) return out;
    const W = diff.cols, H = diff.rows;
    const x0 = Math.max(0, _r(rect[0] * W)), y0 = Math.max(0, _r(rect[1] * H));
    const x1 = Math.min(W, _r((rect[0] + rect[2]) * W));
    const y1 = Math.min(H, _r((rect[1] + rect[3]) * H));
    if (x1 - x0 < 6 || y1 - y0 < 6) return out;
    const roi = diff.roi(new cv.Rect(x0, y0, x1 - x0, y1 - y0));
    const win = roi.isContinuous() ? roi : roi.clone();
    const rows = win.rows, cols = win.cols, d = win.data;
    const col = new Int32Array(cols);
    for (let r = 0; r < rows; r++) {
      const base = r * cols;
      for (let c = 0; c < cols; c++) if (d[base + c]) col[c]++;
    }
    // 文字と文字の間より広い空きで区切る
    const gap = Math.max(3, _r(rows * (gapRatio || 0.45)));
    let start = null, blank = 0;
    const runs = [];
    for (let c = 0; c <= cols; c++) {
      const on = c < cols && col[c] >= 1;
      if (on) {
        if (start === null) start = c;
        blank = 0;
      } else if (start !== null) {
        blank++;
        if (blank >= gap || c === cols) {
          runs.push([start, c - blank + 1]);
          start = null;
          blank = 0;
        }
      }
    }
    for (const [a, b] of runs) {
      if (b - a < 2) continue;                 // 点は捨てる
      // 縦は、その範囲でインクのある行に合わせる
      let top = -1, bottom = -1;
      for (let r = 0; r < rows; r++) {
        const base = r * cols;
        for (let c = a; c < b; c++) {
          if (d[base + c]) { if (top < 0) top = r; bottom = r; break; }
        }
      }
      if (top < 0) continue;
      const pad = Math.max(2, _r((bottom - top + 1) * 0.45));
      out.push([
        Math.max(0, x0 + a - pad) / W,
        Math.max(0, y0 + top - pad) / H,
        Math.min(W, x0 + b + pad) / W - Math.max(0, x0 + a - pad) / W,
        Math.min(H, y0 + bottom + 1 + pad) / H - Math.max(0, y0 + top - pad) / H,
      ]);
    }
    if (win !== roi) win.delete();
    roi.delete();
    return out;
  }

  const LEAD_MISC = '｜|:：;；,，、。・･_＿=＝~〜/／\\＊*+＋"\'`^>＞→ー―—–-';
  const TAIL_MISC = '｜|:；;,，_＿=＝~〜/／\\＊*+＋"\'`^>＞→';
  const OPENERS = '（(「『［[｛{';
  const CLOSERS = '）)」』］]｝}';
  const SIGNS = '+＋-ー―—–';
  // これだけで出来ている文字列は、印刷の括弧や罫線を読んだものなので空にする。
  // `-`（該当なしの意思表示）や `○` `×` は意味を持つので入れない
  const NOISE_ONLY = '（）()「」『』［］[]｛｝{}:：;；,，、。・･_＿=＝~〜/／\\'
                   + '|｜＊*+＋"\'`^ 　>＞<＜→←';
  // 空白の扱いを Python と揃える（trim() と str.strip() は対象が微妙に違う）
  const WS = '[\\t\\n\\v\\f\\r \\u001c-\\u001f\\u0085\\u00a0\\u1680\\u2000-\\u200a'
           + '\\u2028\\u2029\\u202f\\u205f\\u3000\\ufeff]';
  const RE_TRIM = new RegExp(`^${WS}+|${WS}+$`, 'g');
  const RE_WS = new RegExp(WS, 'g');
  const trim = s => String(s).replace(RE_TRIM, '');

  const unbalanced = (t, opener) => {
    const close = CLOSERS[OPENERS.indexOf(opener)];
    return t.split(opener).length > t.split(close).length;
  };
  const unmatchedClose = (t, closer) => {
    const open = OPENERS[CLOSERS.indexOf(closer)];
    return t.split(closer).length > t.split(open).length;
  };

  /**
   * 先頭・末尾に残った記号を落とす。
   * 括弧は対応が取れていないものだけ落とす（`（右）大腿骨頸部骨折` を壊さないため）。
   * 符号（`-3kg`）と、単独の `-`（「該当なし」の意思表示）は残す。
   */
  function trimEdges(text) {
    if (!text) return { text: text || '', notes: [] };
    const original = trim(text);
    const notes = [];
    let out = original;

    let removed = '';
    while (out) {
      const ch = out[0];
      if (SIGNS.includes(ch) && out.length > 1 && /[0-9.]/.test(out[1])) break;
      if (CLOSERS.includes(ch) && unmatchedClose(out, ch)) { /* 落とす */ }
      else if (OPENERS.includes(ch) && unbalanced(out, ch)) { /* 落とす */ }
      else if (LEAD_MISC.includes(ch) && !OPENERS.includes(ch) && !CLOSERS.includes(ch)) { /* 落とす */ }
      else break;
      removed += ch;
      out = trim(out.slice(1));
    }
    if (removed) notes.push(`先頭の記号「${removed}」を削除`);

    removed = '';
    while (out) {
      const ch = out[out.length - 1];
      if (OPENERS.includes(ch) && unbalanced(out, ch)) { /* 落とす */ }
      else if (CLOSERS.includes(ch) && unmatchedClose(out, ch)) { /* 落とす */ }
      else if (TAIL_MISC.includes(ch) && !OPENERS.includes(ch) && !CLOSERS.includes(ch)) { /* 落とす */ }
      else break;
      removed = ch + removed;
      out = trim(out.slice(0, -1));
    }
    if (removed) notes.push(`末尾の記号「${removed}」を削除`);

    out = trim(out);
    // 記号だけ（印刷の括弧や罫線を読んだもの）なら空にする。
    // ただし `-` や `○` は「該当なし」の意思表示なので残す
    const residue = out || original;
    if (residue && [...residue].every(ch => NOISE_ONLY.includes(ch))) {
      return { text: '',
               notes: notes.concat([`記号だけの読み取り「${residue}」を空にしました`]) };
    }
    if (!out) return { text: original, notes: [] };   // 全部消えるなら元のまま
    return { text: out, notes };
  }

  // 1文字あたりの「インクのある列数 ÷ 行の高さ」。実測で 0.24〜1.70 とばらつくため、
  // 幅を持たせて明らかな食い違いだけを拾う（Python の text_check.py と同じ値）。
  const DENSITY_MAX = 1.70;
  const DENSITY_MIN = 0.35;
  const SHORT_RATIO = 0.8;
  const LONG_MARGIN = 2;
  const MIN_EXPECT = 3;
  // 1文字ぶんにも満たない書き込みしか無ければ「記入なし」とみなす
  const EMPTY_DENSITY = 0.25;
  const EMPTY_PENALTY = 0.35;
  const EDGE_PX = 2;

  /** 欄の中の書き込みから、行数・おおよその文字数・端に接しているかを出す。 */
  function writtenShape(warped, blank, rect, sharedDiff) {
    if (!rect || !rect.every(v => Number.isFinite(v))) return null;
    // 差分は1ページに1回作れば足りる。欄ごとに作り直すと重い
    const diff = sharedDiff || markLayer(warped, blank, TEXT_BLANK_DILATE);
    if (!diff) return null;
    const W = diff.cols, H = diff.rows;
    const x0 = Math.max(0, Math.min(W - 1, Math.round(rect[0] * W)));
    const y0 = Math.max(0, Math.min(H - 1, Math.round(rect[1] * H)));
    const x1 = Math.min(W, Math.round((rect[0] + rect[2]) * W));
    const y1 = Math.min(H, Math.round((rect[1] + rect[3]) * H));
    if (x1 - x0 < 8 || y1 - y0 < 6) { if (!sharedDiff) diff.delete(); return null; }
    const roi = diff.roi(new cv.Rect(x0, y0, x1 - x0, y1 - y0));
    const win = roi.isContinuous() ? roi : roi.clone();
    const rows = win.rows, cols = win.cols, d = win.data;
    const rowInk = new Int32Array(rows), colInk = new Int32Array(cols);
    for (let r = 0; r < rows; r++) {
      const base = r * cols;
      for (let c = 0; c < cols; c++) {
        if (d[base + c]) { rowInk[r]++; colInk[c]++; }
      }
    }
    // 行のかたまりを拾う
    const lines = [];
    let start = null;
    for (let r = 0; r <= rows; r++) {
      const on = r < rows && rowInk[r] >= 2;
      if (on && start === null) start = r;
      else if (!on && start !== null) { if (r - start >= 3) lines.push([start, r]); start = null; }
    }
    // 行ごとに「インクのある列数 ÷ 行の高さ」を足す。
    // 端から端までの幅ではなく列数を数えるのは、
    // 欄の中の空きや罫線の残りで水増しされないようにするため。
    let density = 0;
    for (const [top, bottom] of (lines.length ? lines : [[0, rows]])) {
      const lh = Math.max(bottom - top, 1);
      if (lh < 6) continue;
      let n = 0;
      for (let c = 0; c < cols; c++) {
        for (let r = top; r < bottom; r++) if (d[r * cols + c]) { n++; break; }
      }
      if (n) density += n / lh;
    }
    let firstCol = -1, lastCol = -1;
    for (let c = 0; c < cols; c++) {
      if (colInk[c] >= 2) { if (firstCol < 0) firstCol = c; lastCol = c; }
    }
    if (win !== roi) win.delete();
    roi.delete();
    if (!sharedDiff) diff.delete();
    return { density,
             minChars: Math.round(density / DENSITY_MAX),
             maxChars: Math.round(density / DENSITY_MIN),
             lines: lines.length,
             cutLeft: firstCol >= 0 && firstCol <= EDGE_PX,
             cutRight: lastCol >= 0 && lastCol >= cols - 1 - EDGE_PX };
  }

  /**
   * 読めた文字列と書き込みの見た目を突き合わせる。
   * charset のある欄（数字・電話など）は半角が混ざり幅が揃わないので、
   * 文字数の判定はしない。
   */
  function checkText(text, warped, blank, rect, charset, sharedDiff) {
    const out = { penalty: 1, notes: [], expected: null, emptyInk: false,
                  read: [...String(text || '').replace(RE_WS, '')].length };
    const shape = writtenShape(warped, blank, rect, sharedDiff);
    if (!shape) return out;
    out.expected = shape.minChars;
    const lo = shape.minChars, hi = shape.maxChars, read = out.read;
    // 何も書かれていないのに文字が出た場合。罫線や印刷を読んでしまった疑いが濃い。
    // この機能が本来いちばん拾うべき場面なので、文字種による除外もしない。
    if (shape.density < EMPTY_DENSITY && read >= 1) {
      out.emptyInk = true;
      out.notes.push('この欄に書き込みが見当たりません（罫線や印刷を読んだ可能性）');
      out.penalty *= EMPTY_PENALTY;
    } else if (!charset) {
      if (lo >= MIN_EXPECT && read < lo * SHORT_RATIO) {
        out.notes.push(`書かれている量に対して読めた文字が少ない（${lo}文字以上あるはずが${read}文字）`);
        out.penalty *= 0.8;
      } else if (read > hi + LONG_MARGIN) {
        out.notes.push(`書かれている量より読めた文字が多い（多くても${hi}文字のはずが${read}文字）`);
        out.penalty *= 0.8;
      }
    }
    if (shape.cutLeft) {
      out.notes.push('記入が欄の左端に接しています（先頭が切れている可能性）');
      out.penalty *= 0.9;
    }
    if (shape.cutRight) {
      out.notes.push('記入が欄の右端に接しています（末尾が切れている可能性）');
      out.penalty *= 0.9;
    }
    return out;
  }

  global.IkenshoEngine = {
    thresholds, setThresholds, confidenceLevel, waitFor,
    canvasToGrayMat, matToCanvas, flattenIllumination, dewarpPaper,
    registerToRef, matchScore, readBoxes, resolveGroups, readCircle, markLayer,
    detectCircled, resolveStrikes, strikeLines, inkRatio, ringRatio, outsideRatio,
    binarize, TARGET_WIDTH, BLANK_DILATE, TEXT_BLANK_DILATE,
    widenLeft, inkCrop, inkGroups, trimEdges, checkText, writtenShape
  };
})(window);
