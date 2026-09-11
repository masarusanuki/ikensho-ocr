/**
 * 入力ファイル → ページ画像 → 様式判定 → 読み取り、までの一連の処理。
 */
(function (global) {
  'use strict';
  const E = global.IkenshoEngine;
  const L = global.IkenshoLabels;
  // チェック欄の言葉を直した内容の置き場所。様式の設定なので利用者ごとに分けない
  const LABELS_KEY = 'ikensho.labels.v1';

  // 欄ごとの文字種ヒント。書かれる文字が決まっている欄は候補を絞ると精度が上がる。
  const KATAKANA = Array.from({ length: 0x30F6 - 0x30A1 + 1 },
                              (_, i) => String.fromCharCode(0x30A1 + i)).join('');
  const CHARSETS = {
    digits:  '0123456789',
    // 元号は様式で決まっているので、日付欄では数字だけを読む
    date_digits: '0123456789年月日頃 ',
    decimal: '0123456789.',
    wareki:  '0123456789年月日頃明治大正昭和平成令和 ',
    postal:  '0123456789-〒 ',
    // 電話番号は数字とハイフンだけ。印刷された「（ ）」は市外局番の枠なので残さない
    phone:   '0123456789- ',
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

  /** 電話番号を「029-873-3111」の形に整える。 */
  function normalizePhone(text) {
    const parts = String(text || '').split(/[^0-9]+/).filter(Boolean);
    return parts.join('-');
  }

  function filterCharset(text, name) {
    if (!name || !text) return text;
    const allowed = CHARSETS[name];
    if (!allowed) {
      console.warn('未知の文字種です:', name);   // 素通りさせると Python 版とずれる
      return text;
    }
    if (name === 'phone') return normalizePhone(text);
    if (name === 'postal') {
      const d = String(text).replace(/[^0-9]/g, '');
      return d.length >= 7 ? `${d.slice(0, 3)}-${d.slice(3, 7)}` : d;
    }
    const keep = new Set(allowed + '\n');
    const out = Array.from(text).filter(ch => keep.has(ch)).join('');
    return name === 'kana' ? out.trim() : out.split(/\s+/).filter(Boolean).join(' ');
  }

  const MIN_INLIER_RATIO = 0.30;

  class Pipeline {
    constructor(opts) {
      // 様式テンプレートの置き場は ?data=... で差し替えられる。
      // 自前の様式一式を別の場所に置いて読み込ませたい場合に使う。
      const params = new URLSearchParams(location.search);
      this.base = params.get('data') || opts.dataBase || 'data';
      this.vendor = opts.vendorBase || 'vendor';
      this.schema = null;
      this.templates = {};
      this.refs = {};        // `${tid}:${page}` -> cv.Mat（様式判定用・縮小版）
      this.blanks = {};      // `${tid}:${page}` -> cv.Mat（白紙様式・原寸）
      this.dicts = null;
      this.ocrWorker = null;
      this.ocrReady = false;
      this.ocrEnabled = opts.ocrEnabled !== false;
      // チェック欄の後ろの言葉も OCR で確かめるか（管理画面から切り替えられる）
      this.readLabels = opts.readLabels !== false;
      // 日本語のOCRモデル（PP-OCR / ONNX）。置かれていれば tesseract より優先する
      this.pp = global.IkenshoPPOcr
        ? new global.IkenshoPPOcr.PPOcr({ dataBase: this.base, vendorBase: this.vendor })
        : null;
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

    /** 管理画面で直した「チェック欄の言葉」。{"field.opt": "言葉"} */
    static labelOverrides(templateId) {
      try {
        const all = JSON.parse(localStorage.getItem(LABELS_KEY) || '{}');
        return (all && all[templateId]) || {};
      } catch (e) { return {}; }
    }

    /** 直した言葉を保存する。空文字は「直していない」として消す。 */
    static saveLabelOverrides(templateId, labels) {
      let all = {};
      try { all = JSON.parse(localStorage.getItem(LABELS_KEY) || '{}') || {}; }
      catch (e) { all = {}; }
      const clean = {};
      for (const [k, v] of Object.entries(labels || {})) {
        if (typeof v === 'string' && v.trim()) clean[k] = v.trim();
      }
      all[templateId] = clean;
      try { localStorage.setItem(LABELS_KEY, JSON.stringify(all)); return true; }
      catch (e) { return false; }
    }

    async initOcr(onStatus = () => {}) {
      if (!this.ocrEnabled || this.ocrReady) return;
      if (Pipeline.ocrBlocked()) {
        this.ocrEnabled = false;
        return;
      }
      // まず日本語専用モデルを試す。実測でこちらが明らかに正確（DEVELOPER.md）
      if (this.pp && await this.pp.init(onStatus)) {
        this.ocrReady = true;
        this.engineName = `ppocr(${this.pp.model})`;
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
      this.engineName = 'tesseract.js(jpn)';
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

      // --- 3.5) チェック欄の「後ろの言葉」を読む
      // 様式を Word で作り直すと言葉が変わっていることがあるため。
      // 印の付いた枠だけを読む（186枠すべてでは時間がかかりすぎる）。
      const labelReads = {};
      if (this.readLabels !== false && this.ocrEnabled) {
        await this.initOcr(m => onProgress({ phase: 'ocr', message: m }));
        if (this.pp && this.pp.ready) {
          onProgress({ phase: 'ocr', message: 'チェック欄の言葉を読み取っています' });
          for (const [idx, w] of Object.entries(warped)) {
            const only = new Set(readings
              .filter(r => r.checked && w.tplPage.boxes.some(
                b => b.field === r.field && b.opt === r.opt))
              .map(r => `${r.field}.${r.opt}`));
            if (!only.size) continue;
            try {
              Object.assign(labelReads,
                await L.readLabels(w.mat, w.tplPage.boxes, this.pp, only));
            } catch (e) {
              warnings.push('チェック欄の言葉の読み取りに失敗しました（' + e.message + '）');
            }
          }
        }
      }
      const labelOverrides = Pipeline.labelOverrides(templateId);
      const labelInfo = {};
      for (const fid of Object.keys(boxValues)) {
        const f = this.schema.byId[fid];
        if (!f || !f.options) continue;
        f.options.forEach((opt, i) => {
          labelInfo[`${fid}.${i}`] = L.resolve(fid, i, opt, labelReads[`${fid}.${i}`],
                                               labelOverrides, f.options);
        });
      }
      if (Object.values(labelInfo).some(v => v.changed)) {
        warnings.push('チェック欄の言葉が定義と違って読めた箇所があります'
                      + '（管理画面の「チェック欄の言葉」で直せます）');
      }

      // --- 4) テキスト欄OCR
      const textJobs = [];
      for (const [idx, w] of Object.entries(warped)) {
        for (const t of w.tplPage.texts) {
          const f = this.schema.byId[t.field];
          if (!f) continue;
          if (f.type === 'circle') {
            textResults[t.field] = E.readCircle(w.mat, t.rect,
              t.options || f.options || [], !!(t.always_pick || f.always_pick));
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
      // 白紙様式との差分は1ページに1回だけ作る（欄ごとに作ると重い）
      const diffs = {};
      for (const [idx, w] of Object.entries(warped)) {
        const b = this.blanks[`${templateId}:${idx}`];
        const d = b ? E.markLayer(w.mat, b) : null;
        if (d) diffs[idx] = d;
      }
      try {
      for (let i = 0; i < textJobs.length; i++) {
        const { t, f, w } = textJobs[i];
        onProgress({ phase: 'ocr', current: i + 1, total: textJobs.length,
                     message: `テキスト欄を読み取っています（${f.label}）` });
        try {
          this.dateDiff = diffs[w.tplPage.index] || null;
          textResults[t.field] = await this.readText(
            w.mat, t, f, this.blanks[`${templateId}:${w.tplPage.index}`],
            diffs[w.tplPage.index]);
        } catch (e) {
          // 1欄の失敗で1件まるごと落とさない。読めなかった欄だけ要確認にする
          console.error('欄の読み取りに失敗:', f.id, e);
          textResults[t.field] = { value: '', confidence: 0, raw: '', empty: false,
                                   candidates: [],
                                   note: `この欄の読み取りに失敗しました（${e && e.message ? e.message : e}）` };
        }
      }
      } finally {
        Object.values(diffs).forEach(d => d.delete());
      }

      // --- 4.5) 日付欄は年・月・日に分けておく（確認画面で数字だけ直せるように）
      const D = global.IkenshoDates;
      for (const f of Object.values(this.schema.byId)) {
        if (f.kind !== 'date_wareki') continue;
        const entry = textResults[f.id];
        if (!entry) continue;
        // 様式に印刷されている元号は動かさない。本文中に元号らしき文字が
        // 読めても無視する（誤読で30年ずれるのを防ぐ）。
        let era = f.default_era || '';
        let fixed = !!f.default_era;
        if (f.era_field && textResults[f.era_field] && textResults[f.era_field].value) {
          era = textResults[f.era_field].value;
          fixed = false;
        }
        // 専用の読み方（readDate）で年・月・日が取れている場合はそれを使う
        const parts = entry.dateParts
          || D.parse(entry.value || '');
        const canonical = D.canonicalEra(fixed ? era : (parts.era || era));
        entry.date = { year: parts.year, month: parts.month, day: parts.day };
        entry.era = canonical;
        entry.gregorian = D.toGregorian(canonical, parts.year, parts.month, parts.day);
        const text = D.format(entry.date);
        if (text) entry.value = text;
        delete entry.dateParts;
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
        entry.kind = f.kind || '';
        if (f.options) {
          entry.options = f.options;
          const words = f.options.map((o, i) => (labelInfo[`${f.id}.${i}`] || {}).word || o);
          if (words.some((w, i) => w !== f.options[i])) {
            entry.optionWords = words;
            L.applyWords(entry, f.options, words);
          }
          const marks = f.options.map((o, i) => labelInfo[`${f.id}.${i}`]).filter(Boolean);
          if (marks.some(m => m.changed || m.source === '修正')) entry.labelNotes = marks;
        }
        fields[f.id] = entry;
      }

      // --- 6) 確認画面用のページ画像
      const images = {};
      for (const [idx, w] of Object.entries(warped)) {
        images[idx] = E.matToCanvas(w.mat).toDataURL('image/jpeg', 0.82);
        w.mat.delete();
      }

      // 件ごとの目印。操作ログで別の意見書と混ざらないようにするために要る。
      // 氏名などを含めないよう、内容とは無関係な文字列にする。
      const id = 'r' + Date.now().toString(36) +
                 Math.random().toString(36).slice(2, 6);
      const record = { id, fields, pages: pageInfos, templateId, warnings, images,
                       ocrEngine: this.ocrReady ? (this.engineName || 'unknown') : 'none',
                       anonymized: false };
      // 匿名化加工済みデータの扱い（氏名欄が白抜きなら「匿名化済み」）
      const A = global.IkenshoAnonymize;
      // OCR を使っていない場合はテキスト欄が全て空になるので、自動判定はしない
      const canDetect = this.ocrReady;
      if (opts.anonymized || (canDetect && A.looksAnonymized(record, this.schema))) {
        A.apply(record, this.schema, !!opts.anonymized);
        if (opts.anonymized) {
          warnings.push('匿名化加工済みデータとして処理しました（住所・連絡先はマスク済み）');
        }
      }
      return record;
    }

    async readText(warped, t, f, blank, diff) {
      // 測った左端が記入の先頭に食い込んでいることがあるので、
      // 印刷内容にぶつからない範囲で左へ広げてから読む
      const rect = blank ? E.widenLeft(blank, t.rect) : t.rect;
      if (!this.hasInk(warped, rect)) {
        return { value: '', confidence: 0.95, raw: '', empty: true, candidates: [] };
      }
      if (!this.ocrReady) {
        return { value: '', confidence: 0, raw: '', empty: false, candidates: [],
                 note: 'OCR未使用' };
      }
      const charset = t.charset || f.charset || '';
      const multiline = f.type === 'textarea';
      // 日付欄は「年・月・日」の枠が分かっているので専用の読み方をする
      if (f.kind === 'date_wareki' && t.slots && this.pp && this.pp.ready) {
        return await this.readDate(warped, t, f);
      }
      // 白紙様式との差分で「書き込みが無い」と分かる欄は読まない。
      // 読ませると罫線やカッコから文字を作ってしまう（実測で拾い読みが出た）
      const shape = diff ? E.writtenShape(warped, blank, rect, diff) : null;
      if (shape && shape.density < 0.25) {
        return { value: '', confidence: 0.90, raw: '', empty: true, candidates: [],
                 note: 'この欄に書き込みが見当たりません（印刷の罫線だけです）' };
      }
      let text = '', conf = 0;
      if (this.pp && this.pp.ready) {
        // 日本語専用モデル（Python版と同じもの）。
        // 罫線・カッコ・単位を含めたまま読むと精度が落ちるので、
        // 書き込みのある範囲に詰めてから渡す（検算には元の矩形を使う）
        // 日付欄は、印刷されている「年・月・日」を手がかりに分けるので、
        // 書き込みの範囲に詰めると**いちばん右の「日」が落ちる**（印刷なので
        // 書き込みの範囲に入らない）。日付欄だけは詰めない
        const tight = (diff && f.kind !== 'date_wareki')
          ? E.inkCrop(diff, rect) : rect;
        const roi = this.cropMat(warped, tight);
        try {
          const r = await this.pp.read(roi, multiline);
          text = r.text || '';
          conf = r.confidence || 0;
        } catch (e) {
          roi.delete();
          return { value: '', confidence: 0, raw: '', empty: false, candidates: [],
                   note: 'OCR失敗: ' + e.message };
        }
        roi.delete();
      } else {
        const canvas = this.cropForOcr(warped, rect);
        // 欄の形によって適した解析モードが違うので両方試し、確信度の高い方を採る
        const psms = multiline ? [6, 4] : [7, 6];
        for (const psm of psms) {
          try {
            // 文字の種類の制限は LSTM では悪影響が出るため、後段のフィルタで行う
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
      }
      if (f.type !== 'textarea') text = text.split(/\s+/).filter(Boolean).join(' ');
      text = filterCharset(text, charset);
      // 罫線やカッコ由来の記号が端に残っていたら落とす（辞書を引く前に）
      const trimmed = E.trimEdges(text);
      const c = this.dicts.correct(f.id, trimmed.text, conf);
      const entry = { value: c.value, confidence: c.confidence, raw: text,
                      empty: false, candidates: c.candidates };
      if (trimmed.notes.length) {
        entry.corrections = (entry.corrections || []).concat(
          trimmed.notes.map(n => ({ before: '', after: '', reason: n })));
      }
      // 書かれている量・端の接し方と、読めた文字列を突き合わせる
      const chk = E.checkText(entry.value || '', warped, blank, rect, charset, diff);
      entry.expected_chars = chk.expected;
      // 記述の欄に1文字だけというのは、まず記入ではなく罫線やゴミを拾ったもの。
      // 空にして要確認にする。元の読みは raw に残るので「OCR生読み」から戻せる。
      if ((f.type === 'text' || f.type === 'textarea') && !charset &&
          !(f.options && f.options.length) &&
          [...String(entry.value || '').replace(/\s/g, '')].length === 1) {
        entry.value = '';
        entry.confidence = Math.min(entry.confidence || 0, 0.30);
        entry.note = [entry.note,
          '1文字だけ読めましたが、記述としてあり得ないため空にしました（必要なら「OCR生読み」から戻せます）']
          .filter(Boolean).join('／');
      }
      if (chk.notes.length) {
        entry.confidence = Math.round(entry.confidence * chk.penalty * 1000) / 1000;
        entry.note = [entry.note, ...chk.notes].filter(Boolean).join('／');
      }
      if (t.transferred) {
        // 別様式から機械的に写した暫定位置。枠がずれている可能性がある
        entry.confidence *= 0.5;
        entry.note = [entry.note, '欄の位置が暫定です（管理画面のテンプレート編集で調整できます）']
          .filter(Boolean).join('／');
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

    /**
     * 日付欄を読む。
     *
     * 欄には「年」「月」「日」が印刷されているので、**欄全体を1行として読み、
     * その区切りで数字を振り分ける**（Python 版と同じ考え方）。
     *
     * 注意: 書き込みの範囲に詰めてはいけない。「日」は欄のいちばん右に
     * 印刷されており、詰めると落ちて日が取れなくなる（実測でそうなっていた）。
     *
     * 区切りで足りない部分が出たときだけ、年・月・日の枠を囲う範囲を読み直す。
     * 欄には元号の丸印など余分な書き込みが入ることがあり、狭く取った方が
     * 拾えることがあるため。
     */
    async readDate(warped, t, f) {
      const D = global.IkenshoDates;
      const slots = t.slots || {};
      const keys = ['year', 'month', 'day'].filter(k => slots[k]);
      const plausible = (k, v) => v !== null && v !== undefined
        && (k === 'month' ? (v >= 1 && v <= 12)
          : k === 'day' ? (v >= 1 && v <= 31) : (v >= 1 && v <= 99));
      const readOne = async rect => {
        const roi = this.cropMat(warped, rect);
        try {
          const r = await this.pp.read(roi, false);
          return { text: (r.text || '').trim(), conf: r.confidence || 0 };
        } finally {
          roi.delete();
        }
      };

      const whole = await readOne(t.rect);
      const parts = D.parse(whole.text);
      let conf = whole.conf;
      let raw = whole.text;
      const missing = () => ['year', 'month', 'day']
        .filter(k => !plausible(k, parts[k]));

      if (keys.length && missing().length) {
        // 年・月・日の枠だけを囲う範囲で読み直す
        const xs = keys.map(k => slots[k]);
        const union = [
          Math.min(...xs.map(r => r[0])), Math.min(...xs.map(r => r[1])),
          Math.max(...xs.map(r => r[0] + r[2])) - Math.min(...xs.map(r => r[0])),
          Math.max(...xs.map(r => r[1] + r[3])) - Math.min(...xs.map(r => r[1])),
        ];
        const narrow = await readOne(union);
        const guess = D.parse(narrow.text);
        const filled = [];
        for (const k of missing()) {
          if (!plausible(k, guess[k])) continue;
          parts[k] = guess[k];
          filled.push(k);
        }
        if (filled.length) {
          raw += ` / ${narrow.text}`;
          conf = Math.min(conf || 1, narrow.conf || 0.5);
        }
      }

      const got = ['year', 'month', 'day'].filter(k => plausible(k, parts[k])).length;
      for (const k of ['year', 'month', 'day']) {
        if (!plausible(k, parts[k])) parts[k] = null;
      }
      return {
        value: D.format(parts),
        // 全部そろって初めて高い確信度にする（欠けは要確認に出す）
        confidence: got ? Math.min(0.95, (conf || 0.5) * (0.55 + 0.15 * got)) : 0,
        raw, empty: got === 0, candidates: [],
        dateParts: { year: parts.year, month: parts.month, day: parts.day },
        note: got === 3 ? ''
          : '日付の一部が読めませんでした（数字を直接入力できます）',
      };
    }

    /** 認識モデルに渡す切り抜き（余白も拡大もしない生の矩形）。 */
    cropMat(warped, rect, pad = 0.02) {
      const W = warped.cols, H = warped.rows;
      const px = rect[2] * pad * W, py = rect[3] * pad * H;
      const x0 = Math.max(0, Math.round(rect[0] * W - px));
      const y0 = Math.max(0, Math.round(rect[1] * H - py));
      const x1 = Math.min(W, Math.round((rect[0] + rect[2]) * W + px));
      const y1 = Math.min(H, Math.round((rect[1] + rect[3]) * H + py));
      return warped.roi(new cv.Rect(x0, y0, Math.max(4, x1 - x0), Math.max(4, y1 - y0)));
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
