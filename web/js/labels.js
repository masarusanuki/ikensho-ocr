/**
 * チェック欄の「後ろに書いてある言葉」を読む（ブラウザ版）。
 * Python 版 `python/ikensho_ocr/labels.py` と同じ考え方・同じ数値。
 *
 * 様式を Word で作り直すと、チェック欄の並びは同じでも後ろの文字が
 * 変わっていることがある。読み取りのときに枠の右隣を OCR して確かめ、
 * 食い違いは確認画面に出す。読み違えることもあるので**直せる**ようにしてある。
 */
(function (global) {
  'use strict';

  const LABEL_MAX_WIDTH = 9.0;   // 枠の右にどこまでを「その枠の言葉」とみなすか
  const LABEL_GAP = 0.25;        // 枠のすぐ右の空き（枠幅比）
  const LABEL_PAD_Y = 0.45;      // 上下にどれだけ広げるか（枠の高さ比）
  const NEXT_BOX_GAP = 0.6;      // 次の枠の手前で止めるときの空き
  const SAME_ROW = 0.6;          // 同じ行とみなす縦のずれ（枠の高さ比）
  const CHANGED_MAX_SIM = 0.5;   // 定義との似かたがこれ以下なら「違う言葉」
  const CHANGED_MIN_LEN = 3;     // これより短い言葉は読み違えが多いので疑わない

  const KILL = /[\s　:：・.,、。()（）\[\]【】「」]+/g;
  const BOXCHAR = /^[口ロ□■☐▢〇○●]+|[口ロ□■☐▢]+$/g;
  const DASH = /[ー—–—‐\-─―一]/g;

  /** 見比べるための正規化。全角半角・記号・空白・長音の違いを消す。 */
  function normalize(text) {
    if (!text) return '';
    let t = String(text).normalize('NFKC').replace(KILL, '');
    t = t.replace(BOXCHAR, '');
    return t.replace(DASH, 'ー');
  }

  /** 枠の右隣にある言葉の範囲（正規化座標）。同じ行の次の枠の手前で止める。 */
  function labelRect(box, siblings) {
    const [x, y, w, h] = box.rect;
    const x0 = x + w * (1.0 + LABEL_GAP);
    let right = x + w * (1.0 + LABEL_MAX_WIDTH);
    const cy = y + h / 2;
    for (const other of siblings) {
      const [ox, oy, , oh] = other.rect;
      if (ox <= x) continue;
      if (Math.abs((oy + oh / 2) - cy) > h * SAME_ROW) continue;
      right = Math.min(right, ox - w * NEXT_BOX_GAP);
    }
    right = Math.min(Math.max(right, x0 + w * 0.8), 1.0);
    const y0 = Math.max(0, y - h * LABEL_PAD_Y);
    const y1 = Math.min(1, y + h * (1.0 + LABEL_PAD_Y));
    return [x0, y0, right - x0, y1 - y0];
  }

  /** 同じ行に並ぶチェック欄をまとめる。行ごとに1回だけ OCR するため。 */
  function groupRows(boxes) {
    const rows = [];
    const sorted = [...boxes].sort((a, b) => (a.rect[1] - b.rect[1]) || (a.rect[0] - b.rect[0]));
    for (const b of sorted) {
      const cy = b.rect[1] + b.rect[3] / 2;
      let row = rows.find(r => Math.abs(cy - (r[0].rect[1] + r[0].rect[3] / 2)) <= r[0].rect[3] * SAME_ROW);
      if (row) row.push(b); else rows.push([b]);
    }
    rows.forEach(r => r.sort((a, b) => a.rect[0] - b.rect[0]));
    return rows;
  }

  /**
   * 枠の右隣を OCR して、読めた言葉を返す。
   * 1枠ずつ読むと遅く、2〜3文字では読み違えも多いので**行ごとにまとめて読み**、
   * 読めた語の位置から、どの枠の言葉かを振り分ける。
   *
   * @param {cv.Mat} warped テンプレート座標に合わせたグレー画像
   * @param {Array} boxes   そのページのチェック欄
   * @param {object} pp     PPOcr（read() が位置つきで返すもの）
   * @param {Set} only      "field.opt" の集合。渡すとその枠だけ読む
   */
  async function readLabels(warped, boxes, pp, only) {
    const out = {};
    if (!pp || !pp.ready) return out;
    const W = warped.cols, H = warped.rows;
    const rects = new Map(boxes.map(b => [`${b.field}.${b.opt}`, labelRect(b, boxes)]));
    for (const row of groupRows(boxes)) {
      const keys = row.map(b => `${b.field}.${b.opt}`);
      if (only && !keys.some(k => only.has(k))) continue;
      const rs = keys.map(k => rects.get(k));
      const x0 = Math.min(...rs.map(r => r[0])), x1 = Math.max(...rs.map(r => r[0] + r[2]));
      const y0 = Math.min(...rs.map(r => r[1])), y1 = Math.max(...rs.map(r => r[1] + r[3]));
      const px0 = Math.round(x0 * W), py0 = Math.round(y0 * H);
      const px1 = Math.round(x1 * W), py1 = Math.round(y1 * H);
      if (px1 - px0 < 8 || py1 - py0 < 8) continue;
      const crop = warped.roi(new cv.Rect(Math.max(0, px0), Math.max(0, py0),
        Math.min(W, px1) - Math.max(0, px0), Math.min(H, py1) - Math.max(0, py0))).clone();
      // 四角い枠そのものは「口」と読まれてしまうので、白で塗りつぶしておく
      for (const b of boxes) {
        const [bx, by, bw, bh] = b.rect;
        const ex = bw * 0.25, ey = bh * 0.25;
        const cx0 = Math.max(0, Math.round((bx - ex) * W) - px0);
        const cy0 = Math.max(0, Math.round((by - ey) * H) - py0);
        const cx1 = Math.min(crop.cols, Math.round((bx + bw + ex) * W) - px0);
        const cy1 = Math.min(crop.rows, Math.round((by + bh + ey) * H) - py0);
        if (cx1 > cx0 && cy1 > cy0) {
          const r = crop.roi(new cv.Rect(cx0, cy0, cx1 - cx0, cy1 - cy0));
          r.setTo(new cv.Scalar(255));
          r.delete();
        }
      }
      let res = null;
      try {
        res = await pp.read(crop, false);
      } catch (e) {
        console.warn('チェック欄の言葉を読めませんでした:', e.message);
      }
      crop.delete();
      if (!res || !res.tokens || !res.tokens.length) continue;
      // 読めた語を、位置がいちばん重なる枠に振り分ける
      const parts = {};
      for (const tk of res.tokens) {
        const lx = tk.x0 + px0, rx = tk.x1 + px0;
        const cx = (lx + rx) / 2 / W;
        let best = null, cover = 0;
        for (const key of keys) {
          const [rx0, , rw] = rects.get(key);
          const lo = rx0, hi = rx0 + rw;
          let ov = Math.max(0, Math.min(hi, rx / W) - Math.max(lo, lx / W));
          if (cx >= lo && cx <= hi) ov += rw;     // 中心が入っている枠を優先
          if (ov > cover) { best = key; cover = ov; }
        }
        if (best) (parts[best] = parts[best] || []).push([lx, tk.text]);
      }
      for (const [key, items] of Object.entries(parts)) {
        items.sort((a, b) => a[0] - b[0]);
        const text = normalize(items.map(i => i[1]).join(''));
        if (text) out[key] = text;
      }
    }
    return out;
  }

  /** 2つの言葉がどれだけ似ているか 0..1（Python の difflib と同じ考え方）。 */
  function similarity(a, b) {
    a = normalize(a); b = normalize(b);
    if (!a || !b) return 0;
    return 2 * matches(a, b) / (a.length + b.length);
  }

  // difflib.SequenceMatcher と同じ「一致する部分の合計」を再帰で求める
  function matches(a, b) {
    if (!a.length || !b.length) return 0;
    let best = [0, 0, 0];
    const counts = new Map();
    for (let i = 0; i < b.length; i++) {
      const k = b[i];
      if (!counts.has(k)) counts.set(k, []);
      counts.get(k).push(i);
    }
    let j2len = new Map();
    for (let i = 0; i < a.length; i++) {
      const newj2 = new Map();
      for (const j of (counts.get(a[i]) || [])) {
        const k = (j2len.get(j - 1) || 0) + 1;
        newj2.set(j, k);
        if (k > best[2]) best = [i - k + 1, j - k + 1, k];
      }
      j2len = newj2;
    }
    const [ai, bj, size] = best;
    if (!size) return 0;
    return size + matches(a.slice(0, ai), b.slice(0, bj))
                + matches(a.slice(ai + size), b.slice(bj + size));
  }

  /**
   * その枠に使う言葉を決める。
   * 優先順位は **管理画面で直した言葉 > 定義の言葉**。
   * 読めた言葉はそのまま採らず、定義と食い違うときの合図として使う
   * （ラベルは小さく、OCR は4割ほど読み違えるため）。
   */
  function resolve(fieldId, opt, expected, read, overrides, siblings) {
    const key = `${fieldId}.${opt}`;
    const out = { word: expected, source: '定義', expected, read: read || '', changed: false };
    const fixed = overrides && overrides[key];
    if (fixed) { out.word = fixed; out.source = '修正'; return out; }
    const nr = normalize(read), ne = normalize(expected);
    if (!nr || nr.length < CHANGED_MIN_LEN) return out;
    if (ne && (nr.indexOf(ne) >= 0 || ne.indexOf(nr) >= 0)) return out;
    if (similarity(read, expected) > CHANGED_MAX_SIM) return out;
    for (const other of (siblings || [])) {
      const no = normalize(other);
      if (other === expected || !no) continue;
      if (nr.indexOf(no) >= 0 || similarity(read, other) > CHANGED_MAX_SIM) return out;
    }
    out.changed = true;
    out.note = '定義と違う言葉が読めました。確かめてください';
    return out;
  }

  /**
   * 項目の値を、実物の言葉（または管理画面で直した言葉）に置き換える。
   * 出力の JSON はチェックの**言葉**が要なので、値そのものを差し替える。
   */
  function applyWords(entry, options, words) {
    if (options.every((o, i) => o === words[i])) return;
    const table = {};
    options.forEach((o, i) => { table[o] = words[i]; });
    if (typeof entry.value === 'string') {
      entry.value = table[entry.value] !== undefined ? table[entry.value] : entry.value;
    } else if (Array.isArray(entry.value)) {
      entry.value = entry.value.map(v => (table[v] !== undefined ? table[v] : v));
    }
  }

  global.IkenshoLabels = { normalize, labelRect, groupRows, readLabels, similarity, resolve,
                           applyWords, CHANGED_MAX_SIM, CHANGED_MIN_LEN };
})(window);
