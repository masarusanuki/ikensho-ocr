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
    const W = warped.cols, H = warped.rows;
    const out = [];
    for (const b of boxes) {
      const [rx, ry, rw, rh] = b.rect;
      let x = Math.round(rx * W), y = Math.round(ry * H);
      const w = Math.max(3, Math.round(rw * W)), h = Math.max(3, Math.round(rh * H));
      x = Math.max(0, Math.min(x, W - w)); y = Math.max(0, Math.min(y, H - h));
      const fill = fillRatio(bw, x, y, w, h);
      const mark = diff ? markRatio(diff, x, y, w, h) : 0;
      const halo = haloRatio(bw, x, y, w, h);
      const score = combinedScore(fill, mark, !!diff);
      out.push({ field: b.field, opt: b.opt, fill, mark, halo, score, rect: b.rect,
                 circled: false, checked: score >= 0.5,
                 confidence: scoreConfidence(score) });
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
      detectCircled(rs);
      const detail = rs.map(r => ({ opt: r.opt, fill: +r.fill.toFixed(4),
                                    halo: +(r.halo || 0).toFixed(4), circled: !!r.circled,
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
  const LEAD_MISC = '｜|:：;；,，、。・･_＿=＝~〜/／\\＊*+＋"\'`^>＞→ー―—–-';
  const TAIL_MISC = '｜|:；;,，_＿=＝~〜/／\\＊*+＋"\'`^>＞→';
  const OPENERS = '（(「『［[｛{';
  const CLOSERS = '）)」』］]｝}';
  const SIGNS = '+＋-ー―—–';
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
    const diff = sharedDiff || markLayer(warped, blank);
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
    detectCircled,
    binarize, TARGET_WIDTH,
    widenLeft, trimEdges, checkText, writtenShape
  };
})(window);
