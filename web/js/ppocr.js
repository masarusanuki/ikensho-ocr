/**
 * ブラウザで日本語のOCRモデル（PP-OCR / ONNX）を動かす。
 *
 * tesseract.js の日本語は、この様式の文字（かな・医療用語・手書き風）に弱い。
 * 実測（bench/ocr_truth.json）では、同じ切り抜きに対して
 * 文字正解率が tesseract 50.5% ／ PP-OCRv4 日本語専用 78.0% だった。
 * そこで **Python 版と同じ認識モデル**を onnxruntime-web で動かす。
 *
 * - 文字の検出（どこに字があるか）はしない。**欄の位置はテンプレートで分かっている**ので、
 *   切り抜きをそのまま認識に回す。複数行の欄だけ、インクの行で切り分ける
 * - モデルが置かれていなければ tesseract.js に戻る（同梱をやめても動く）
 * - 前処理と復号は Python 版（rapidocr）と同じ規則に揃えている。
 *   片方だけ直すと結果がずれるので注意
 */
(function (global) {
  'use strict';

  const REC_HEIGHT = 48;          // PP-OCR の認識モデルは高さ48で学習されている
  const MAX_WIDTH = 2400;         // 長い記述欄でも扱える上限
  const MIN_LINE_PX = 6;          // これ未満の高さの行は無視する
  const PAD = 10;                      // 認識に渡すときに足す白い余白（画素）
  // 引き伸ばしたあとに輪郭を立てる強さ（Python 版の ocr.SHARPEN と同じ値）
  const SHARPEN = 0.6;
  // 文字の位置を見つけるモデルの設定（rapidocr の config.yaml と同じ値）
  const DET_LIMIT = 736;          // 短辺をここまで拡大する
  const DET_MAX_SIDE = 1600;      // 重くなりすぎないための上限
  const DET_THRESH = 0.3;
  const DET_BOX_THRESH = 0.5;
  const DET_UNCLIP = 0.35;        // 見つけた枠を少し広げる

  function loadScript(src) {
    return new Promise((resolve, reject) => {
      const el = document.createElement('script');
      el.src = src;
      el.onload = () => resolve();
      el.onerror = () => reject(new Error(`${src} を読み込めません`));
      document.head.appendChild(el);
    });
  }

  class PPOcr {
    constructor(opts) {
      this.dataBase = (opts && opts.dataBase) || 'data';
      this.vendorBase = (opts && opts.vendorBase) || 'vendor';
      this.session = null;
      this.det = null;
      this.chars = null;
      this.model = null;          // 使っているモデルの名前
      this.failed = false;
    }

    get ready() { return !!this.session; }

    /** 置かれているモデルの一覧（data/ocr/index.json）。 */
    async list() {
      try {
        const res = await fetch(`${this.dataBase}/ocr/index.json`);
        if (!res.ok) return [];
        const idx = await res.json();
        return idx.models || [];
      } catch (e) {
        return [];
      }
    }

    /**
     * モデルを読み込む。置かれていなければ false を返す（呼び側は tesseract に戻る）。
     */
    async init(onProgress, wanted) {
      if (this.session) return true;
      if (this.failed) return false;
      const models = await this.list();
      if (!models.length) { this.failed = true; return false; }
      const pick = (wanted && models.find(m => m.key === wanted)) || models[0];
      const say = m => { if (onProgress) onProgress(m); };
      try {
        say('日本語OCRモデルを読み込んでいます…');
        if (!global.ort) await loadScript(`${this.vendorBase}/ort.wasm.min.js`);
        const ort = global.ort;
        // ここは動的 import() で読まれるので、相対パスのままでは
        // 「モジュール指定子を解決できない」と言われる。絶対URLにする
        ort.env.wasm.wasmPaths = new URL(`${this.vendorBase}/`, location.href).href;
        // SharedArrayBuffer が使えない配信（COOP/COEP なし）でも動くようにする
        ort.env.wasm.numThreads = 1;
        ort.env.logLevel = 'error';

        const dictUrl = `${this.dataBase}/ocr/${pick.key}/${pick.keys}`;
        const modelUrl = `${this.dataBase}/ocr/${pick.key}/${pick.rec}`;
        const detUrl = pick.det
          ? `${this.dataBase}/ocr/${pick.key}/${pick.det}` : '';
        const [dictText, modelBuf] = await Promise.all([
          fetch(dictUrl).then(r => {
            if (!r.ok) throw new Error(`文字辞書を読み込めません（${r.status}）`);
            return r.text();
          }),
          fetch(modelUrl).then(r => {
            if (!r.ok) throw new Error(`モデルを読み込めません（${r.status}）`);
            return r.arrayBuffer();
          }),
        ]);
        // Python 版（rapidocr の CTCLabelDecode）と同じ並び:
        //   ['blank'] + 辞書の各行 + [' ']
        const lines = dictText.split('\n').map(s => s.replace(/\r$/, ''));
        while (lines.length && lines[lines.length - 1] === '') lines.pop();
        this.chars = ['blank'].concat(lines, [' ']);
        this.session = await ort.InferenceSession.create(modelBuf, {
          executionProviders: ['wasm'],
          graphOptimizationLevel: 'all',
        });
        this.model = pick.key;
        this.note = pick.note || '';
        // 文字の位置を見つけるモデル（あれば使う。無くても動く）
        if (detUrl) {
          try {
            const buf = await fetch(detUrl).then(r => {
              if (!r.ok) throw new Error(String(r.status));
              return r.arrayBuffer();
            });
            this.det = await ort.InferenceSession.create(buf, {
              executionProviders: ['wasm'], graphOptimizationLevel: 'all',
            });
          } catch (e) {
            console.warn('文字位置の検出モデルは使いません:', e.message);
            this.det = null;
          }
        }
        say(`日本語OCRモデル（${pick.key}）を読み込みました`);
        return true;
      } catch (e) {
        console.error('PP-OCR の読み込みに失敗:', e);
        this.failed = true;
        this.error = e.message;
        return false;
      }
    }

    /**
     * 文字のある場所を見つける（DBNet）。
     *
     * ブラウザ版はこれが無く、切り抜き全体を1行として認識に流していた。
     * そのため日付欄のように**数字が離れて並ぶ欄**で、罫線や元号の丸印を
     * 数字と読んでしまっていた（実測で `8年11月20日` が `28年11月20日`）。
     * Python 版（rapidocr）は先に検出を通しているので、そこに揃える。
     *
     * 後処理は rapidocr の設定と同じ値にしてある（threshold 0.3 /
     * box_thresh 0.5 / unclip_ratio 1.6 / 膨張あり）。
     */
    async detect(gray) {
      if (!this.det) return null;
      const ort = global.ort;
      // 短辺が 736 以上になるように拡大し、32の倍数に合わせる（rapidocr と同じ）
      const minSide = Math.min(gray.rows, gray.cols);
      let scale = minSide > 0 ? DET_LIMIT / minSide : 1;
      let w = Math.max(32, Math.round(gray.cols * scale / 32) * 32);
      let h = Math.max(32, Math.round(gray.rows * scale / 32) * 32);
      // 大きすぎると重いので上限をかける
      const cap = DET_MAX_SIDE / Math.max(w, h);
      if (cap < 1) {
        w = Math.max(32, Math.floor(w * cap / 32) * 32);
        h = Math.max(32, Math.floor(h * cap / 32) * 32);
      }
      const resized = new cv.Mat();
      cv.resize(gray, resized, new cv.Size(w, h), 0, 0, cv.INTER_LINEAR);
      const src = resized.isContinuous() ? resized : resized.clone();
      const d = src.data;
      const n = w * h;
      const data = new Float32Array(3 * n);
      for (let i = 0; i < n; i++) {
        const v = (d[i] / 255 - 0.5) / 0.5;
        data[i] = v; data[n + i] = v; data[2 * n + i] = v;
      }
      if (src !== resized) src.delete();
      resized.delete();

      const feeds = {};
      feeds[this.det.inputNames[0]] = new ort.Tensor('float32', data, [1, 3, h, w]);
      const out = await this.det.run(feeds);
      const prob = out[this.det.outputNames[0]];
      const [, , ph, pw] = prob.dims;
      const p = prob.data;

      // しきい値で2値化 → 輪郭 → 外接矩形（我々の画像は既に傾き補正済みなので
      // 回転矩形までは要らない）
      const mask = new cv.Mat(ph, pw, cv.CV_8UC1);
      const m = mask.data;
      for (let i = 0; i < ph * pw; i++) m[i] = p[i] > DET_THRESH ? 255 : 0;
      const k = cv.getStructuringElement(cv.MORPH_RECT, new cv.Size(2, 2));
      cv.dilate(mask, mask, k);
      const contours = new cv.MatVector();
      const hier = new cv.Mat();
      cv.findContours(mask, contours, hier, cv.RETR_LIST, cv.CHAIN_APPROX_SIMPLE);
      const boxes = [];
      for (let i = 0; i < contours.size(); i++) {
        const c = contours.get(i);
        const r = cv.boundingRect(c);
        c.delete();
        if (r.width < 3 || r.height < 3) continue;
        // 枠の中の確からしさ（rapidocr の box_thresh と同じ考え方）
        let sum = 0, cnt = 0;
        for (let y = r.y; y < r.y + r.height; y++) {
          for (let x = r.x; x < r.x + r.width; x++) { sum += p[y * pw + x]; cnt++; }
        }
        if (!cnt || sum / cnt < DET_BOX_THRESH) continue;
        // 少し広げる（unclip）。文字の端が切れると読み落とす
        const pad = Math.max(1, Math.round(Math.min(r.width, r.height) * DET_UNCLIP));
        const x0 = Math.max(0, r.x - pad), y0 = Math.max(0, r.y - pad);
        const x1 = Math.min(pw, r.x + r.width + pad);
        const y1 = Math.min(ph, r.y + r.height + pad);
        // 元の切り抜きの座標系に戻す
        boxes.push({
          x0: x0 / pw * gray.cols, y0: y0 / ph * gray.rows,
          x1: x1 / pw * gray.cols, y1: y1 / ph * gray.rows,
        });
      }
      contours.delete(); hier.delete(); mask.delete(); k.delete();
      return orderBoxes(boxes);
    }

    /**
     * 認識に渡す前の下ごしらえ（Python 版 ocr.prepare_roi と同じ）。
     *
     * 小さい切り抜きは拡大し、**白い余白を足す**。
     * 余白が無いと、枠いっぱいに書かれた数字を読み落とす
     * （実測で `11` が `1` になった）。
     */
    /**
     * 認識に渡す前に、読みやすい大きさに整える。
     *
     * **解像度の低い入力への備え。** 人が読める程度に写っていても、
     * 1文字が10px前後だと認識モデルは読めない。Python 版の
     * `ocr.upscale_for_ocr` と同じ考え方にしてある。
     *   - 2倍を超える引き伸ばしは Lanczos（Cubic はにじんで細い線が消える）
     *   - 引き伸ばしたあとに軽く輪郭を立てて、にじみを戻す
     */
    prepare(gray) {
      const scale = Math.max(1, REC_HEIGHT / Math.max(gray.rows, 1));
      let work = gray;
      if (scale > 1.01) {
        work = new cv.Mat();
        cv.resize(gray, work, new cv.Size(Math.round(gray.cols * scale),
                                          Math.round(gray.rows * scale)),
                  0, 0, scale >= 2 ? cv.INTER_LANCZOS4 : cv.INTER_CUBIC);
        if (scale >= 2 && SHARPEN > 0) {
          const blur = new cv.Mat();
          cv.GaussianBlur(work, blur, new cv.Size(0, 0), 1.0);
          cv.addWeighted(work, 1 + SHARPEN, blur, -SHARPEN, 0, work);
          blur.delete();
        }
      }
      const padded = new cv.Mat();
      cv.copyMakeBorder(work, padded, PAD, PAD, PAD, PAD,
                        cv.BORDER_CONSTANT, new cv.Scalar(255, 255, 255, 255));
      if (work !== gray) work.delete();
      return padded;
    }

    /**
     * 1行ぶんの画像（cv.Mat・グレースケール）を読む。
     * 前処理は Python 版と同じ: 高さ48に合わせ、(値/255 - 0.5) / 0.5 に正規化する。
     */
    async readLine(raw, alreadyPadded) {
      const ort = global.ort;
      const gray = alreadyPadded ? raw.clone() : this.prepare(raw);
      const ratio = gray.cols / Math.max(gray.rows, 1);
      const width = Math.min(MAX_WIDTH, Math.max(8, Math.ceil(REC_HEIGHT * ratio)));
      const resized = new cv.Mat();
      cv.resize(gray, resized, new cv.Size(width, REC_HEIGHT), 0, 0, cv.INTER_LINEAR);
      const src = resized.isContinuous() ? resized : resized.clone();
      const d = src.data;
      const n = REC_HEIGHT * width;
      const data = new Float32Array(3 * n);
      for (let i = 0; i < n; i++) {
        const v = (d[i] / 255 - 0.5) / 0.5;
        data[i] = v;                 // 3チャンネルに同じ値を入れる（グレースケール）
        data[n + i] = v;
        data[2 * n + i] = v;
      }
      if (src !== resized) src.delete();
      resized.delete();
      gray.delete();

      const input = new ort.Tensor('float32', data, [1, 3, REC_HEIGHT, width]);
      const feeds = {};
      feeds[this.session.inputNames[0]] = input;
      const out = await this.session.run(feeds);
      const tensor = out[this.session.outputNames[0]];
      return this.decode(tensor);
    }

    /** CTC の復号（同じ文字の連続をまとめ、blank を捨てる）。 */
    decode(tensor) {
      const [, steps, classes] = tensor.dims;
      const p = tensor.data;
      let text = '';
      let sum = 0, count = 0, prev = -1;
      for (let t = 0; t < steps; t++) {
        let best = 0, bestP = -1;
        const off = t * classes;
        for (let c = 0; c < classes; c++) {
          const v = p[off + c];
          if (v > bestP) { bestP = v; best = c; }
        }
        if (best !== prev && best !== 0) {
          text += this.chars[best] === undefined ? '' : this.chars[best];
          sum += bestP;
          count++;
        }
        prev = best;
      }
      return { text, confidence: count ? sum / count : 0 };
    }

    /**
     * 欄の切り抜きを読む。
     *
     * まず文字の位置を見つけ、見つかった塊ごとに認識する（Python 版と同じ流れ）。
     * 検出モデルが無い場合は、行のかたまりで切って読む。
     *
     * 戻り値の `tokens` には、読めた文字と**切り抜きの中での位置**が入る。
     * 日付欄で数字を年・月・日に振り分けるのに使う。
     */
    async read(gray, multiline) {
      if (!this.session) return { text: '', confidence: 0, tokens: [] };
      const prepared = this.prepare(gray);
      const sx = gray.cols / prepared.cols;      // 余白を足した分の縮尺
      const sy = gray.rows / prepared.rows;
      let boxes = null;
      try {
        boxes = await this.detect(prepared);
      } catch (e) {
        console.warn('文字位置の検出に失敗したので、そのまま読みます:', e.message);
        boxes = null;
      }
      const tokens = [];
      let sum = 0;
      if (boxes && boxes.length) {
        for (const b of boxes) {
          const w = Math.round(b.x1 - b.x0), h = Math.round(b.y1 - b.y0);
          if (w < 3 || h < 3) continue;
          const roi = prepared.roi(new cv.Rect(
            Math.max(0, Math.round(b.x0)), Math.max(0, Math.round(b.y0)),
            Math.min(w, prepared.cols - Math.round(b.x0)),
            Math.min(h, prepared.rows - Math.round(b.y0))));
          try {
            const r = await this.readLine(roi, true);
            if (r.text.trim()) {
              tokens.push({ text: r.text, conf: r.confidence, row: b.row,
                            x0: (b.x0 - PAD) * sx, x1: (b.x1 - PAD) * sx,
                            y0: (b.y0 - PAD) * sy, y1: (b.y1 - PAD) * sy });
              sum += r.confidence;
            }
          } finally {
            roi.delete();
          }
        }
      } else {
        // 検出が使えない場合（行のかたまりで切る）
        const lines = multiline ? lineBoxes(gray) : [[0, gray.rows]];
        for (const [top, bottom] of lines) {
          if (bottom - top < MIN_LINE_PX) continue;
          const roi = gray.roi(new cv.Rect(0, top, gray.cols, bottom - top));
          try {
            const r = await this.readLine(roi);
            if (r.text.trim()) {
              tokens.push({ text: r.text, conf: r.confidence,
                            x0: 0, x1: gray.cols, y0: top, y1: bottom });
              sum += r.confidence;
            }
          } finally {
            roi.delete();
          }
        }
      }
      prepared.delete();
      if (!tokens.length) return { text: '', confidence: 0, tokens: [] };
      // 行が変わるところで改行、同じ行は空白でつなぐ
      let text = tokens[0].text;
      for (let i = 1; i < tokens.length; i++) {
        const prev = tokens[i - 1], cur = tokens[i];
        const sameLine = (cur.row !== undefined && prev.row !== undefined)
          ? cur.row === prev.row
          : Math.abs(cur.y0 - prev.y0) < (cur.y1 - cur.y0) * 0.6;
        text += (sameLine ? ' ' : '\n') + cur.text;
      }
      return { text, confidence: sum / tokens.length, tokens };
    }
  }

  /**
   * 見つけた枠を「行ごと」にまとめて、読む順（上から下・左から右）に並べる。
   *
   * 枠の高さを目安に行を判定する。切り抜きの高さで判定すると、
   * 記述欄（数行）で**行が混ざる**（実測で1行目が最後に来て、
   * 文章の先頭が落ちていた）。
   */
  function orderBoxes(boxes) {
    if (boxes.length < 2) return boxes;
    const heights = boxes.map(b => b.y1 - b.y0).sort((a, b) => a - b);
    const med = heights[Math.floor(heights.length / 2)] || 1;
    const sorted = boxes.slice().sort((a, b) => a.y0 - b.y0);
    const lines = [];
    for (const b of sorted) {
      const mid = (b.y0 + b.y1) / 2;
      const line = lines.find(l => Math.abs(l.mid - mid) < med * 0.6);
      if (line) {
        line.items.push(b);
        line.mid = line.items.reduce((s, x) => s + (x.y0 + x.y1) / 2, 0) / line.items.length;
      } else {
        lines.push({ mid, items: [b] });
      }
    }
    lines.sort((a, b) => a.mid - b.mid);
    lines.forEach((l, row) => {
      l.items.sort((a, b) => a.x0 - b.x0);
      l.items.forEach(b => { b.row = row; });   // 行の切り替わりが分かるように
    });
    return lines.flatMap(l => l.items);
  }

  /**
   * インクのある行のかたまりを返す。
   * 認識モデルは1行ずつしか読めないので、記述欄はここで切り分ける。
   */
  function lineBoxes(gray) {
    const bw = global.IkenshoEngine.binarize(gray);
    const src = bw.isContinuous() ? bw : bw.clone();
    const rows = src.rows, cols = src.cols, d = src.data;
    const ink = new Int32Array(rows);
    for (let r = 0; r < rows; r++) {
      const base = r * cols;
      let n = 0;
      for (let c = 0; c < cols; c++) if (d[base + c]) n++;
      ink[r] = n;
    }
    if (src !== bw) src.delete();
    bw.delete();
    // 1行の中でも濃さは揺れるので、その欄の最大値に対する割合で見る
    const peak = Math.max(...ink);
    const thresh = Math.max(2, peak * 0.06);
    const out = [];
    let start = null;
    for (let r = 0; r <= rows; r++) {
      const on = r < rows && ink[r] >= thresh;
      if (on && start === null) start = r;
      else if (!on && start !== null) {
        if (r - start >= MIN_LINE_PX) {
          // 上下に少し余白を足す（はみ出した部分が切れないように）
          out.push([Math.max(0, start - 2), Math.min(rows, r + 2)]);
        }
        start = null;
      }
    }
    return out.length ? out : [[0, rows]];
  }

  global.IkenshoPPOcr = { PPOcr, lineBoxes };
})(window);
