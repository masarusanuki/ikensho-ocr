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
     * 1行ぶんの画像（cv.Mat・グレースケール）を読む。
     * 前処理は Python 版と同じ: 高さ48に合わせ、(値/255 - 0.5) / 0.5 に正規化する。
     */
    async readLine(gray) {
      const ort = global.ort;
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
     * 複数行の欄は、インクのある行のかたまりごとに切って読み、改行でつなぐ。
     */
    async read(gray, multiline) {
      if (!this.session) return { text: '', confidence: 0 };
      const boxes = multiline ? lineBoxes(gray) : [[0, gray.rows]];
      const parts = [];
      let sum = 0;
      for (const [top, bottom] of boxes) {
        if (bottom - top < MIN_LINE_PX) continue;
        const roi = gray.roi(new cv.Rect(0, top, gray.cols, bottom - top));
        try {
          const r = await this.readLine(roi);
          if (r.text.trim()) { parts.push(r.text); sum += r.confidence; }
        } finally {
          roi.delete();
        }
      }
      if (!parts.length) return { text: '', confidence: 0 };
      return { text: parts.join('\n'), confidence: sum / parts.length };
    }
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
