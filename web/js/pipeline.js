/**
 * 入力ファイル → ページ画像 → 様式判定 → 読み取り、までの一連の処理。
 */
(function (global) {
  'use strict';
  const E = global.IkenshoEngine;

  // 欄ごとの文字種ヒント。書かれる文字が決まっている欄は候補を絞ると精度が上がる。
  const KATAKANA = Array.from({ length: 0x30F6 - 0x30A1 + 1 },
                              (_, i) => String.fromCharCode(0x30A1 + i)).join('');
  const CHARSETS = {
    digits:  '0123456789',
    decimal: '0123456789.',
    wareki:  '0123456789年月日頃明治大正昭和平成令和 ',
    postal:  '0123456789-〒 ',
    phone:   '0123456789()-  ',
    kana:    KATAKANA + 'ー・ 　',
  };

  // 日本語の文字（tesseract は文字ごとに空白を入れるので、その除去に使う）
  const CJK_RE = /[\u3000-\u30ff\u3400-\u9fff\uf900-\ufaff\uff66-\uff9f]/;

  /**
   * 日本語の文字と文字の間に入った空白を詰める。
   * tesseract の日本語モデルは「石 井 と め」のように1文字ずつ切って返すため、
   * そのままでは辞書照合にかからない。英数字の間の空白は意味があるので残す。
   */
  function joinJapanese(text) {
    if (!text) return text;
    let out = '';
    for (let i = 0; i < text.length; i++) {
      if (text[i] === ' ' && i > 0 && i < text.length - 1 &&
          CJK_RE.test(text[i - 1]) && CJK_RE.test(text[i + 1])) continue;
      out += text[i];
    }
    return out;
  }

  function filterCharset(text, name) {
    const allowed = CHARSETS[name];
    if (!allowed || !text) return text;
    const keep = new Set(allowed + '\n');
    const out = Array.from(text).filter(ch => keep.has(ch)).join('');
    return name === 'kana' ? out.trim() : out.split(/\s+/).filter(Boolean).join(' ');
  }

  const MIN_INLIER_RATIO = 0.30;

  class Pipeline {
    constructor(opts) {
      this.base = opts.dataBase || 'data';
      this.vendor = opts.vendorBase || 'vendor';
      this.schema = null;
      this.templates = {};
      this.refs = {};        // `${tid}:${page}` -> cv.Mat（様式判定用・縮小版）
      this.blanks = {};      // `${tid}:${page}` -> cv.Mat（白紙様式・原寸）
      this.dicts = null;
      this.ocrWorker = null;
      this.ocrReady = false;
      this.ocrEnabled = opts.ocrEnabled !== false;
    }

    // ---------------------------------------------------------- 初期化
    async init(onStatus = () => {}) {
      onStatus('画像処理ライブラリを準備しています…');
      await E.waitFor(() => global.cv && global.cv.Mat, 90000, 'OpenCV.js');

      onStatus('項目定義と様式テンプレートを読み込んでいます…');
      const schemaRaw = await fetchJson(`${this.base}/ikensho.schema.json`);
      this.schema = buildSchema(schemaRaw);

      const index = await fetchJson(`${this.base}/templates/index.json`);
      for (const tid of index.templates) {
        const t = await fetchJson(`${this.base}/templates/${tid}.json`);
        t.id = t.id || tid;
        this.templates[t.id] = t;
      }

      onStatus('様式の参照画像を読み込んでいます…');
      for (const tpl of Object.values(this.templates)) await this.loadTemplateRefs(tpl);

      onStatus('医療辞書を読み込んでいます…');
      this.dicts = await new global.IkenshoDicts.Dictionaries().load(`${this.base}/dict`);

      onStatus('準備完了');
      return this;
    }

    /** テンプレートの参照画像を読み込む（管理画面からの追加読み込み用）。 */
    async loadTemplateRefs(tpl) {
      for (const p of tpl.pages) {
        const key = `${tpl.id}:${p.index}`;
        if (this.refs[key]) continue;
        const img = await loadImage(`${this.base}/templates/refs/${p.ref}`);
        const c = document.createElement('canvas');
        c.width = img.naturalWidth; c.height = img.naturalHeight;
        c.getContext('2d').drawImage(img, 0, 0);
        this.refs[key] = E.canvasToGrayMat(c);

        // 白紙様式（差分によるマーク抽出に使う。無くても動作する）
        try {
          const bimg = await loadImage(`${this.base}/templates/blanks/${p.blank || p.ref}`);
          const bc = document.createElement('canvas');
          bc.width = p.width; bc.height = p.height;
          bc.getContext('2d').drawImage(bimg, 0, 0, p.width, p.height);
          this.blanks[key] = E.canvasToGrayMat(bc);
        } catch (e) { /* 白紙が無い様式は枠内インク率のみで判定する */ }
      }
    }

    /**
     * ブラウザの制約で OCR を使えない状況かを判定する。
     * file:// で直接開いた場合、ページの生成元が null になるため
     * OCR ワーカーが必要なスクリプトを読み込めない。
     */
    static ocrBlocked() {
      return location.protocol === 'file:';
    }

    async initOcr(onStatus = () => {}) {
      if (!this.ocrEnabled || this.ocrReady) return;
      if (Pipeline.ocrBlocked()) {
        this.ocrEnabled = false;
        return;
      }
      onStatus('日本語OCRを準備しています（初回のみ時間がかかります）…');
      const T = global.Tesseract;
      this.ocrWorker = await T.createWorker('jpn', 1, {
        workerPath: resolveUrl(`${this.vendor}/tesseract.worker.min.js`),
        corePath: resolveUrl(`${this.vendor}/tesseract-core-simd.wasm.js`),
        langPath: resolveUrl(`${this.vendor}/__lang__`) === `${this.vendor}/__lang__`
          ? this.vendor : global.IKENSHO_BUNDLE.__langPath,
        gzip: true,
      });
      await this.ocrWorker.setParameters({
        preserve_interword_spaces: '1',
        tessedit_pageseg_mode: T.PSM ? T.PSM.SINGLE_LINE : '7',
      });
      this.ocrReady = true;
    }

    // ---------------------------------------------------------- 入力読込
    /** File → [{canvas, source, sourcePage, fromPdf}] */
    async loadFile(file) {
      const name = file.name || '(名称未設定)';
      if (/\.pdf$/i.test(name) || file.type === 'application/pdf') {
        return await this.loadPdf(file, name);
      }
      const bmp = await createImageBitmap(file);
      const scale = Math.min(1, 2400 / Math.max(bmp.width, bmp.height));
      const c = document.createElement('canvas');
      c.width = Math.round(bmp.width * scale);
      c.height = Math.round(bmp.height * scale);
      c.getContext('2d').drawImage(bmp, 0, 0, c.width, c.height);
      return [{ canvas: c, source: name, sourcePage: 1, fromPdf: false }];
    }

    async loadPdf(file, name) {
      const pdfjs = global.pdfjsLib;
      pdfjs.GlobalWorkerOptions.workerSrc = resolveUrl(`${this.vendor}/pdf.worker.min.mjs`);
      const buf = await file.arrayBuffer();
      const doc = await pdfjs.getDocument({ data: buf }).promise;
      const pages = [];
      for (let i = 1; i <= doc.numPages; i++) {
        const page = await doc.getPage(i);
        const base = page.getViewport({ scale: 1 });
        const scale = E.TARGET_WIDTH / base.width;
        const vp = page.getViewport({ scale });
        const c = document.createElement('canvas');
        c.width = Math.round(vp.width); c.height = Math.round(vp.height);
        const ctx = c.getContext('2d');
        ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, c.width, c.height);
        await page.render({ canvasContext: ctx, viewport: vp }).promise;
        pages.push({ canvas: c, source: name, sourcePage: i, fromPdf: true });
      }
      return pages;
    }

    // ---------------------------------------------------------- 照合
    /** 1ページがどの様式の何ページ目かを判定し、位置合わせして返す。 */
    matchPage(gray, restrictTo) {
      let best = null;
      for (const [tid, tpl] of Object.entries(this.templates)) {
        if (restrictTo && tid !== restrictTo) continue;
        for (const p of tpl.pages) {
          const ref = this.refs[`${tid}:${p.index}`];
          if (!ref) continue;
          const r = E.registerToRef(gray, ref);
          if (!r.H) continue;
          if (r.inliers < E.thresholds.MIN_INLIERS) { r.H.delete(); continue; }
          if (r.inliers / Math.max(r.matches, 1) < MIN_INLIER_RATIO) { r.H.delete(); continue; }
          const score = E.matchScore(r.inliers, r.matches);
          if (best && best.score >= score) { r.H.delete(); continue; }
          if (best) best.H.delete();
          best = { templateId: tid, pageIndex: p.index, H: r.H, score,
                   inliers: r.inliers, matches: r.matches, tplPage: p };
        }
      }
      return best;
    }

    warpToTemplate(gray, match) {
      const ref = this.refs[`${match.templateId}:${match.pageIndex}`];
      const scale = match.tplPage.width / ref.cols;
      const S = cv.matFromArray(3, 3, cv.CV_64F, [scale, 0, 0, 0, scale, 0, 0, 0, 1]);
      const Hf = new cv.Mat();
      cv.gemm(S, match.H, 1, new cv.Mat(), 0, Hf);
      const out = new cv.Mat();
      cv.warpPerspective(gray, out, Hf, new cv.Size(match.tplPage.width, match.tplPage.height),
                         cv.INTER_LINEAR, cv.BORDER_CONSTANT, new cv.Scalar(255));
      S.delete(); Hf.delete();
      return out;
    }

    // ---------------------------------------------------------- 実行
    /**
     * ページ群を処理して1件のレコードを返す。
     * PDF・画像・カメラ撮影が混在してよく、ページ順も問わない。
     */
    async process(pages, opts = {}) {
      const onProgress = opts.onProgress || (() => {});
      const isCamera = opts.camera !== false;
      const warnings = [];
      const pageInfos = [];
      const warped = {};    // pageIndex -> {mat, canvas, score}
      let templateId = null;

      // --- 1) ページごとに様式判定
      const prepared = [];
      for (let i = 0; i < pages.length; i++) {
        const p = pages[i];
        onProgress({ phase: 'align', current: i + 1, total: pages.length,
                     message: `${p.source} ${p.sourcePage}ページ目を解析しています…` });
        await sleep(0);
        let gray = E.canvasToGrayMat(p.canvas);
        let dewarped = false;
        if (!p.fromPdf && isCamera) {
          const dw = E.dewarpPaper(gray);
          if (dw) { gray.delete(); gray = dw; dewarped = true; }
          const flat = E.flattenIllumination(gray);
          gray.delete(); gray = flat;
        }
        const m = this.matchPage(gray);
        prepared.push({ page: p, gray, match: m, dewarped });
      }

      // --- 2) 様式を多数決で統一（1ページずつ撮影された場合の取りこぼし防止）
      const votes = {};
      for (const pr of prepared) if (pr.match) votes[pr.match.templateId] = (votes[pr.match.templateId] || 0) + pr.match.score;
      const winner = Object.keys(votes).sort((a, b) => votes[b] - votes[a])[0];

      for (const pr of prepared) {
        const p = pr.page;
        const m = pr.match && pr.match.templateId === winner ? pr.match : null;
        pageInfos.push({
          source: p.source, sourcePage: p.sourcePage,
          templateId: m ? m.templateId : null, pageIndex: m ? m.pageIndex : null,
          score: m ? m.score : 0, inliers: m ? m.inliers : 0,
          dewarped: pr.dewarped, matched: !!m,
        });
        if (!m) {
          warnings.push(`${p.source} ${p.sourcePage}ページ目: 様式を判別できませんでした`);
          pr.gray.delete();
          if (pr.match) pr.match.H.delete();
          continue;
        }
        templateId = m.templateId;
        if (warped[m.pageIndex] && warped[m.pageIndex].score >= m.score) {
          warnings.push(`${p.source} ${p.sourcePage}ページ目: ${m.pageIndex}ページ目が重複しているため無視しました`);
          pr.gray.delete(); m.H.delete();
          continue;
        }
        if (warped[m.pageIndex]) warped[m.pageIndex].mat.delete();
        const w = this.warpToTemplate(pr.gray, m);
        warped[m.pageIndex] = { mat: w, score: m.score, tplPage: m.tplPage };
        pr.gray.delete(); m.H.delete();
      }

      if (!templateId) {
        return { fields: {}, pages: pageInfos, templateId: null,
                 warnings: warnings.concat(['読み取れるページがありませんでした']),
                 images: {} };
      }

      const tpl = this.templates[templateId];
      const missing = tpl.pages.map(p => p.index).filter(i => !warped[i]);
      if (missing.length) warnings.push('未取得のページ: ' + missing.map(i => `${i}ページ目`).join('、'));

      // --- 3) チェックボックス判定
      let readings = [];
      const textResults = {};
      for (const [idx, w] of Object.entries(warped)) {
        readings = readings.concat(
          E.readBoxes(w.mat, w.tplPage.boxes, this.blanks[`${templateId}:${idx}`]));
      }
      const boxValues = E.resolveGroups(readings, this.schema);

      // --- 4) テキスト欄OCR
      const textJobs = [];
      for (const [idx, w] of Object.entries(warped)) {
        for (const t of w.tplPage.texts) {
          const f = this.schema.byId[t.field];
          if (!f) continue;
          if (f.type === 'circle') {
            textResults[t.field] = E.readCircle(w.mat, t.rect, t.options || f.options || []);
            continue;
          }
          textJobs.push({ t, f, w });
        }
      }
      if (this.ocrEnabled) await this.initOcr(m => onProgress({ phase: 'ocr', message: m }));
      if (!this.ocrEnabled && textJobs.length) {
        warnings.push(Pipeline.ocrBlocked()
          ? 'テキスト欄のOCRは使っていません（ファイルを直接開いた場合、'
            + 'ブラウザの制約でOCRを起動できません）。チェックボックスはすべて読み取っています。'
          : 'テキスト欄のOCRは使っていません。チェックボックスはすべて読み取っています。');
      }
      for (let i = 0; i < textJobs.length; i++) {
        const { t, f, w } = textJobs[i];
        onProgress({ phase: 'ocr', current: i + 1, total: textJobs.length,
                     message: `テキスト欄を読み取っています（${f.label}）` });
        textResults[t.field] = await this.readText(w.mat, t, f);
      }

      // --- 5) レコード組み立て
      const fields = {};
      for (const f of this.schema.order.map(id => this.schema.byId[id])) {
        let entry = boxValues[f.id] || textResults[f.id] || { value: null, confidence: 0 };
        entry = Object.assign({}, entry);
        if (entry.value === undefined) entry.value = null;
        if (entry.confidence === undefined) entry.confidence = 0;
        entry.confidence = Math.round(entry.confidence * 1000) / 1000;
        entry.level = E.confidenceLevel(entry.confidence);
        entry.label = f.label; entry.type = f.type;
        entry.section = f.sectionTitle; entry.page = f.page;
        if (f.options) entry.options = f.options;
        fields[f.id] = entry;
      }

      // --- 6) 確認画面用のページ画像
      const images = {};
      for (const [idx, w] of Object.entries(warped)) {
        images[idx] = E.matToCanvas(w.mat).toDataURL('image/jpeg', 0.82);
        w.mat.delete();
      }

      const record = { fields, pages: pageInfos, templateId, warnings, images,
                       ocrEngine: this.ocrReady ? 'tesseract.js(jpn)' : 'none',
                       anonymized: false };
      // 匿名化加工済みデータの扱い（氏名欄が白抜きなら「匿名化済み」）
      const A = global.IkenshoAnonymize;
      if (opts.anonymized || A.looksAnonymized(record, this.schema)) {
        A.apply(record, this.schema, !!opts.anonymized);
        if (opts.anonymized) {
          warnings.push('匿名化加工済みデータとして処理しました（住所・連絡先はマスク済み）');
        }
      }
      return record;
    }

    async readText(warped, t, f) {
      const rect = t.rect;
      if (!this.hasInk(warped, rect)) {
        return { value: '', confidence: 0.95, raw: '', empty: true, candidates: [] };
      }
      if (!this.ocrReady) {
        return { value: '', confidence: 0, raw: '', empty: false, candidates: [],
                 note: 'OCR未使用' };
      }
      const canvas = this.cropForOcr(warped, rect);
      const charset = t.charset || f.charset || '';
      // 欄の形によって適した解析モードが違うので両方試し、確信度の高い方を採る
      const psms = f.type === 'textarea' ? [6, 4] : [7, 6];
      let text = '', conf = 0;
      for (const psm of psms) {
        try {
          // 文字種の制限は LSTM では悪影響が出るため、後段のフィルタで行う
          await this.ocrWorker.setParameters({
            tessedit_pageseg_mode: String(psm),
            tessedit_char_whitelist: '',
          });
          const { data } = await this.ocrWorker.recognize(canvas);
          const got = joinJapanese((data.text || '').trim());
          const c = (data.confidence || 0) / 100;
          if (got && (c > conf || !text)) { text = got; conf = c; }
        } catch (e) {
          if (!text) {
            return { value: '', confidence: 0, raw: '', empty: false, candidates: [],
                     note: 'OCR失敗: ' + e.message };
          }
        }
      }
      if (f.type !== 'textarea') text = text.split(/\s+/).filter(Boolean).join(' ');
      text = filterCharset(text, charset);
      const c = this.dicts.correct(f.id, text, conf);
      const entry = { value: c.value, confidence: c.confidence, raw: text,
                      empty: false, candidates: c.candidates };
      if (t.transferred) {
        // 別様式から機械的に写した暫定位置。枠がずれている可能性がある
        entry.confidence *= 0.5;
        entry.note = '欄の位置が暫定です（管理画面のテンプレート編集で調整できます）';
      }
      return entry;
    }

    hasInk(warped, rect, threshold = 0.008) {
      const W = warped.cols, H = warped.rows;
      const x0 = Math.max(0, Math.round(rect[0] * W)), y0 = Math.max(0, Math.round(rect[1] * H));
      const x1 = Math.min(W, Math.round((rect[0] + rect[2]) * W));
      const y1 = Math.min(H, Math.round((rect[1] + rect[3]) * H));
      if (x1 - x0 < 4 || y1 - y0 < 4) return false;
      const roi = warped.roi(new cv.Rect(x0, y0, x1 - x0, y1 - y0));
      const bw = E.binarize(roi);
      const ratio = cv.countNonZero(bw) / (bw.rows * bw.cols);
      roi.delete(); bw.delete();
      return ratio > threshold;
    }

    cropForOcr(warped, rect, pad = 0.02) {
      const W = warped.cols, H = warped.rows;
      const px = rect[2] * pad * W, py = rect[3] * pad * H;
      const x0 = Math.max(0, Math.round(rect[0] * W - px));
      const y0 = Math.max(0, Math.round(rect[1] * H - py));
      const x1 = Math.min(W, Math.round((rect[0] + rect[2]) * W + px));
      const y1 = Math.min(H, Math.round((rect[1] + rect[3]) * H + py));
      const roi = warped.roi(new cv.Rect(x0, y0, Math.max(4, x1 - x0), Math.max(4, y1 - y0)));
      const scale = Math.max(1, 48 / roi.rows);
      const big = new cv.Mat();
      cv.resize(roi, big, new cv.Size(Math.round(roi.cols * scale), Math.round(roi.rows * scale)),
                0, 0, cv.INTER_CUBIC);
      const padded = new cv.Mat();
      cv.copyMakeBorder(big, padded, 12, 12, 12, 12, cv.BORDER_CONSTANT, new cv.Scalar(255));
      const canvas = E.matToCanvas(padded);
      roi.delete(); big.delete(); padded.delete();
      return canvas;
    }

    /** 確認画面で1項目分の切り抜き画像を作る（元画像と読み取り値の突き合わせ用）。 */
    cropPreview(imageDataUrl, rect, pad = 0.35) {
      return { rect, pad };
    }
  }

  function buildSchema(raw) {
    const byId = {}, order = [], sections = [];
    for (const sec of raw.sections) {
      const fields = [];
      for (const f of sec.fields) {
        const item = Object.assign({}, f, { sectionId: sec.id, sectionTitle: sec.title });
        byId[f.id] = item; order.push(f.id); fields.push(item);
      }
      sections.push({ id: sec.id, title: sec.title, fields });
    }
    return { version: raw.version, formName: raw.form_name, byId, order, sections };
  }

  /**
   * 単一HTMLファイル版では、外部ファイルの代わりに埋め込み済みの
   * Blob URL を使う。通常版では受け取ったパスをそのまま返す。
   */
  function resolveUrl(path) {
    const b = global.IKENSHO_BUNDLE;
    return (b && b[path]) ? b[path] : path;
  }

  function loadImage(src) {
    return new Promise((resolve, reject) => {
      const img = new Image();
      img.onload = () => resolve(img);
      img.onerror = () => reject(new Error('画像を読み込めません: ' + src));
      img.src = resolveUrl(src);
    });
  }

  const sleep = ms => new Promise(r => setTimeout(r, ms));

  function fetchJson(url) {
    return fetch(resolveUrl(url)).then(r => {
      if (!r.ok) throw new Error(`${url} を取得できません (${r.status})`);
      return r.json();
    });
  }

  global.IkenshoPipeline = Pipeline;
  global.IkenshoResolveUrl = resolveUrl;
})(window);
