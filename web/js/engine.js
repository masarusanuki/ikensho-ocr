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
    MARK_EMPTY_MAX: 0.012,  // 白紙との差分がこれ未満なら未記入
    MARK_FILLED_MIN: 0.030, // 白紙との差分がこれ以上なら記入あり
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

  function boxConfidence(fill) {
    if (fill <= thresholds.EMPTY_MAX) return Math.min(1, 0.55 + (thresholds.EMPTY_MAX - fill) / thresholds.EMPTY_MAX * 0.45);
    if (fill >= thresholds.FILLED_MIN) return Math.min(1, 0.55 + (fill - thresholds.FILLED_MIN) / 0.35 * 0.45);
    const mid = (thresholds.EMPTY_MAX + thresholds.FILLED_MIN) / 2, span = (thresholds.FILLED_MIN - thresholds.EMPTY_MAX) / 2;
    return 0.15 + Math.abs(fill - mid) / span * 0.35;
  }

  const MARK_MARGIN = 0.45;   // 枠の外側どこまでを見るか。はみ出したレ点を拾う

  /**
   * 白紙様式との差分をとり、手書きのマークだけを残した2値画像を作る。
   * 枠線・ラベル・説明文が消えるので、枠からはみ出したレ点や丸印も拾える。
   */
  function markLayer(warped, blank) {
    if (!blank || blank.cols !== warped.cols || blank.rows !== warped.rows) return null;
    const scan = binarize(warped);
    const base = binarize(blank);
    const k = cv.getStructuringElement(cv.MORPH_RECT, new cv.Size(3, 3));
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

  function unit(v, lo, hi) {
    if (hi <= lo) return 0;
    return Math.max(0, Math.min(1, (v - lo) / (hi - lo)));
  }

  /**
   * 枠内インク率と差分マークの大きい方を「記入の強さ」とする。
   * 枠内に収まったチェックは fill が、はみ出したレ点や丸印は mark が拾う。
   */
  function combinedScore(fill, mark, hasDiff) {
    let s = unit(fill, thresholds.EMPTY_MAX, thresholds.FILLED_MIN);
    if (hasDiff) s = Math.max(s, unit(mark, thresholds.MARK_EMPTY_MAX, thresholds.MARK_FILLED_MIN));
    return s;
  }

  const scoreConfidence = s => Math.min(1, 0.45 + Math.abs(s - 0.5) * 1.10);

  function readBoxes(warped, boxes, blank) {
    const bw = binarize(warped);
    const diff = markLayer(warped, blank);
    const W = warped.cols, H = warped.rows;
    const out = [];
    for (const b of boxes) {
      const [rx, ry, rw, rh] = b.rect;
      let x = Math.round(rx * W), y = Math.round(ry * H);
      const w = Math.max(3, Math.round(rw * W)), h = Math.max(3, Math.round(rh * H));
      x = Math.max(0, Math.min(x, W - w)); y = Math.max(0, Math.min(y, H - h));
      const fill = fillRatio(bw, x, y, w, h);
      const mark = diff ? markRatio(diff, x, y, w, h) : 0;
      const score = combinedScore(fill, mark, !!diff);
      out.push({ field: b.field, opt: b.opt, fill, mark, score, rect: b.rect,
                 checked: score >= 0.5, confidence: scoreConfidence(score) });
    }
    bw.delete();
    if (diff) diff.delete();
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
      const detail = rs.map(r => ({ opt: r.opt, fill: +r.fill.toFixed(4),
                                    mark: +(r.mark || 0).toFixed(4),
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
  function readCircle(warped, rect, options) {
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
    const sorted = [...scores].sort((a, b) => a - b);
    const base = sorted[Math.floor(n / 2)];
    const excess = scores.map(s => s - base);
    const top = excess.indexOf(Math.max(...excess));
    const rank = [...excess].sort((a, b) => b - a);
    const margin = rank[0] - (rank[1] || 0);
    const detail = scores.map((s, i) => ({ opt: i, score: +s.toFixed(4) }));
    if (rank[0] <= 0.012) return { value: null, confidence: 0.2, detail };
    return { value: options[top], confidence: Math.min(1, 0.30 + margin / 0.05 * 0.70), detail };
  }

  global.IkenshoEngine = {
    thresholds, setThresholds, confidenceLevel, waitFor,
    canvasToGrayMat, matToCanvas, flattenIllumination, dewarpPaper,
    registerToRef, matchScore, readBoxes, resolveGroups, readCircle, markLayer,
    binarize, TARGET_WIDTH
  };
})(window);
