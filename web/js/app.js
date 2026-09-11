/** アプリ全体の制御。画面切り替え、ファイル受け取り、読み取り実行、保存。 */
(function (global) {
  'use strict';
  const esc = s => global.IkenshoUtil.esc(s);
  // 保存先は利用者のトークンごとに分ける（同じ端末を複数人が使っても履歴が混ざらない）
  const S = () => global.IkenshoSession;
  const STORAGE_KEY = () => S().key('ikensho.records.v1');
  const SETTINGS_KEY = () => S().key('ikensho.settings.v1');
  const DEFAULT_SETTINGS = { EMPTY_MAX: 0.10, FILLED_MIN: 0.28, CONF_HIGH: 0.80, CONF_MID: 0.50, MIN_INLIERS: 25 };

  class App {
    constructor() {
      this.files = [];
      this.records = [];
      this.current = 0;
      this.settings = Object.assign({}, DEFAULT_SETTINGS, readJson(SETTINGS_KEY()) || {});
      this.pipeline = new global.IkenshoPipeline({ dataBase: 'data', vendorBase: 'vendor' });
      this.review = null;
      this.admin = null;
    }

    async start() {
      this.bindUi();
      this.setStatus('起動しています…');
      try {
        await new Promise(res => {
          if (global.pdfjsLib) return res();
          global.addEventListener('pdfjs-ready', res, { once: true });
          setTimeout(res, 15000);
        });
        await this.pipeline.init(m => this.setStatus(m));
      } catch (e) {
        this.setStatus('起動に失敗しました: ' + e.message, true);
        return;
      }
      global.IkenshoEngine.setThresholds(this.settings);
      this.schema = this.pipeline.schema;
      this.applyOcrAvailability();
      this.checkSamples();
      this.checkDocs();
      this.review = new global.IkenshoReview(this);
      this.admin = new global.IkenshoAdmin(this);
      this.restore();
      if (global.IkenshoSession.migrated) {
        this.toast('この端末に残っていた以前の記録を引き継ぎました（管理画面で確認できます）');
      }
      this.setStatus('準備ができました。ファイルを読み込んでください。');
      await this.loadFromQuery();
    }

    // -------------------------------------------------------------- 画面
    bindUi() {
      document.querySelectorAll('nav.tabs button').forEach(b => {
        b.addEventListener('click', () => this.showView(b.dataset.view));
      });

      const drop = document.getElementById('drop');
      ['dragenter', 'dragover'].forEach(ev => drop.addEventListener(ev, e => {
        e.preventDefault(); drop.classList.add('over');
      }));
      ['dragleave', 'drop'].forEach(ev => drop.addEventListener(ev, e => {
        e.preventDefault(); drop.classList.remove('over');
      }));
      drop.addEventListener('drop', e => this.addFiles(e.dataTransfer.files));

      document.getElementById('btn-pick').addEventListener('click',
        () => document.getElementById('file-input').click());
      document.getElementById('btn-camera').addEventListener('click',
        () => document.getElementById('camera-input').click());
      document.getElementById('file-input').addEventListener('change', e => this.addFiles(e.target.files));
      document.getElementById('camera-input').addEventListener('change', e => this.addFiles(e.target.files));
      document.getElementById('btn-clear').addEventListener('click', () => { this.files = []; this.renderFiles(); });
      document.getElementById('btn-run').addEventListener('click', () => this.run());

      document.getElementById('record-select').addEventListener('change', e => {
        this.current = +e.target.value;
        this.review.show(this.records[this.current]);
      });

      document.getElementById('btn-export-json').addEventListener('click',
        () => this.exportAll('json'));
      document.getElementById('btn-export-csv').addEventListener('click',
        () => this.exportAll('csv'));
      document.getElementById('btn-export-form-json').addEventListener('click',
        () => this.exportAll('form'));
      document.getElementById('btn-export-json-one').addEventListener('click', () => {
        const r = this.records[this.current];
        if (!r) return this.toast('出力する件がありません', true);
        if (global.IkenshoOpLog) global.IkenshoOpLog.flush();
        this.op('export', { count: 1, note: 'JSON（1件）' });
        global.IkenshoExport.exportJson([r], this.schema,
          `ikensho_${this.recordTitle(r) || 'record'}.json`);
      });
      document.getElementById('btn-import').addEventListener('click',
        () => document.getElementById('import-input').click());
      document.getElementById('btn-drop-all-images').addEventListener('click',
        () => this.dropAllImages());
      document.getElementById('import-input').addEventListener('change', e => this.importJson(e));
    }

    /**
     * ?sample=ファイル名 が付いていれば、そのサンプルを取り込んで読み取りを始める。
     * サンプル一覧の「検証する」から呼ばれる。
     */
    async loadFromQuery() {
      const params = new URLSearchParams(location.search);
      const names = params.getAll('sample').filter(Boolean);
      if (!names.length) return;
      this.setStatus('サンプルを取り込んでいます…');
      const files = [];
      for (const n of names) {
        const safe = n.replace(/[^A-Za-z0-9._\-]/g, '');
        try {
          const res = await fetch(`samples/${encodeURIComponent(safe)}`);
          if (!res.ok) throw new Error(String(res.status));
          const blob = await res.blob();
          files.push(new File([blob], safe, { type: blob.type || 'application/pdf' }));
        } catch (e) {
          this.setStatus(`サンプル ${safe} を取り込めませんでした`, true);
          return;
        }
      }
      this.files = this.files.concat(files);
      this.renderFiles();
      this.showView('upload');
      await this.run();
    }

    /** ドキュメントが開けない環境（ファイルを直接開いた場合）では説明を出す。 */
    async checkDocs() {
      const note = document.getElementById('docs-missing');
      if (!note) return;
      if (location.protocol === 'file:') { note.hidden = false; return; }
      try {
        const res = await fetch('docs/index.html', { method: 'HEAD' });
        note.hidden = res.ok;
      } catch (e) {
        note.hidden = false;
      }
    }

    /** 配信環境に動作確認用サンプルが置いてあればリンクを出す。 */
    async checkSamples() {
      if (global.IkenshoPipeline.ocrBlocked()) return;   // 単一ファイル版では出さない
      try {
        const res = await fetch('samples/', { method: 'HEAD' });
        if (res.ok) document.getElementById('samples-link').hidden = false;
      } catch (e) { /* 無ければ出さない */ }
    }

    /** file:// で開いた場合は OCR を使えないので、その旨を画面に出す。 */
    applyOcrAvailability() {
      if (!global.IkenshoPipeline.ocrBlocked()) return;
      const box = document.getElementById('opt-ocr');
      box.checked = false;
      box.disabled = true;
      const label = box.closest('label');
      label.style.opacity = '.6';
      label.title = 'ファイルを直接開いた場合、ブラウザの制約でOCRを起動できません';
      const note = document.createElement('div');
      note.className = 'warnbox';
      note.style.marginTop = '12px';
      note.innerHTML =
        '<strong>テキスト欄のOCRは使えません</strong>' +
        '<p style="margin:6px 0 0">このファイルを直接開いた場合、ブラウザの制約でOCRを起動できません。' +
        '<strong>チェックボックス186項目の読み取りはすべて動作します。</strong>' +
        'テキスト欄は確認画面で入力してください。</p>' +
        '<p style="margin:6px 0 0">OCRも使いたい場合は、Web版（サーバに置く）または' +
        'Windows版インストーラをご利用ください。</p>';
      document.getElementById('drop').after(note);
    }

    showView(name) {
      document.querySelectorAll('nav.tabs button').forEach(b =>
        b.setAttribute('aria-selected', String(b.dataset.view === name)));
      document.querySelectorAll('.view').forEach(v =>
        v.hidden = (v.id !== 'view-' + name));
      if (name === 'admin' && this.admin) this.admin.render();
      if (name === 'records') this.renderRecords();
    }

    setStatus(msg, isError) {
      const el = document.getElementById('status');
      el.textContent = msg;
      el.className = 'status' + (isError ? ' err' : '');
    }

    toast(msg, isError) { this.setStatus(msg, isError); }

    // ------------------------------------------------------------ 入力
    addFiles(list) {
      for (const f of list) this.files.push(f);
      this.renderFiles();
    }

    renderFiles() {
      const ul = document.getElementById('filelist');
      ul.innerHTML = this.files.map((f, i) => `
        <li><span class="name">${esc(f.name)}</span>
            <span class="meta">${(f.size / 1024).toFixed(0)} KB</span>
            <button class="btn sm" data-i="${i}">削除</button></li>`).join('');
      ul.querySelectorAll('button[data-i]').forEach(b => b.addEventListener('click', () => {
        this.files.splice(+b.dataset.i, 1); this.renderFiles();
      }));
      document.getElementById('btn-run').disabled = this.files.length === 0;
    }

    /** 操作ログに1件残す。 */
    op(action, detail) {
      if (global.IkenshoOpLog) global.IkenshoOpLog.add(action, detail || {});
    }

    // ------------------------------------------------------------ 実行
    async run() {
      const btn = document.getElementById('btn-run');
      const prog = document.getElementById('prog');
      btn.disabled = true; prog.hidden = false; prog.value = 0;
      const started = Date.now();
      // ファイル名には氏名が入っていることが多いので記録しない（件数だけ残す）
      this.op('read_start', { count: this.files.length });
      this.pipeline.ocrEnabled = document.getElementById('opt-ocr').checked;
      const split = document.getElementById('opt-split').checked;

      try {
        this.setStatus('ファイルを展開しています…');
        let pages = [];
        for (const f of this.files) {
          pages = pages.concat(await this.pipeline.loadFile(f));
        }
        const groups = split ? await this.groupPages(pages) : [pages];
        this.setStatus(`${groups.length} 件として読み取ります`);

        for (let gi = 0; gi < groups.length; gi++) {
          const rec = await this.pipeline.process(groups[gi], {
            anonymized: document.getElementById('opt-anon').checked,
            onProgress: p => {
              const base = gi / groups.length * 100;
              const step = (p.total ? p.current / p.total : 0) / groups.length * 100;
              prog.value = Math.min(99, base + step);
              this.setStatus(`[${gi + 1}/${groups.length}] ${p.message || ''}`);
            }
          });
          rec.readAt = new Date().toISOString();
          this.records.push(rec);
        }
        prog.value = 100;
        this.persist();
        this.current = this.records.length - 1;
        this.refreshRecordSelect();
        this.review.show(this.records[this.current]);
        this.files = []; this.renderFiles();
        this.setStatus(`読み取りが完了しました（${groups.length} 件）。確認・編集に進んでください。`);
        this.op('read_done', {
          count: groups.length,
          note: `${((Date.now() - started) / 1000).toFixed(1)}秒 / ${pages.length}ページ`,
        });
        this.showView('review');
      } catch (e) {
        console.error(e);
        this.op('read_error', { note: scrubNames(e.message) });
        this.setStatus('読み取り中にエラーが発生しました: ' + e.message, true);
      } finally {
        btn.disabled = this.files.length === 0;
        setTimeout(() => { prog.hidden = true; }, 800);
      }
    }

    /**
     * ページ群を「1件ずつ」に区切る。
     * 様式の1ページ目が現れるたびに新しい件として扱うため、
     * 2ページのPDFを何件分まとめて入れても、1ページずつ撮影しても正しく分かれる。
     */
    async groupPages(pages) {
      const groups = [];
      let cur = null;
      for (let i = 0; i < pages.length; i++) {
        this.setStatus(`ページの並びを判定しています（${i + 1}/${pages.length}）`);
        const p = pages[i];
        let idx = null;
        const gray = global.IkenshoEngine.canvasToGrayMat(p.canvas);
        try {
          const m = this.pipeline.matchPage(gray);
          if (m) { idx = m.pageIndex; m.H.delete(); }
        } finally { gray.delete(); }
        p._pageIndex = idx;
        if (cur === null || idx === 1 || (idx !== null && cur.some(q => q._pageIndex === idx))) {
          cur = []; groups.push(cur);
        }
        cur.push(p);
      }
      return groups;
    }

    touch() { this.persist(); this.renderRecords(); }

    // ------------------------------------------------------------ 保存
    persist() {
      try {
        const slim = this.records.map(r => {
          const c = Object.assign({}, r);
          // 画像は容量が大きいので保存対象から外す
          delete c.images;
          return c;
        });
        localStorage.setItem(STORAGE_KEY(), JSON.stringify(slim));
      } catch (e) { /* 容量超過時は保存しない */ }
    }

    restore() {
      const saved = readJson(STORAGE_KEY());
      if (Array.isArray(saved) && saved.length) {
        this.records = saved.map(r => Object.assign({ images: {} }, r));
        this.current = 0;
        this.refreshRecordSelect();
        this.review.show(this.records[0]);
      } else {
        this.review.show(null);
      }
    }

    saveSettings() {
      global.IkenshoEngine.setThresholds(this.settings);
      try { localStorage.setItem(SETTINGS_KEY(), JSON.stringify(this.settings)); }
      catch (e) { this.toast('この環境では設定を保存できません（今回の読み取りには反映されます）', true); }
    }

    // ------------------------------------------------------------ 一覧
    recordTitle(r) {
      const n = r.fields && r.fields.applicant_name && r.fields.applicant_name.value;
      return (n && String(n).trim()) || '';
    }

    refreshRecordSelect() {
      const sel = document.getElementById('record-select');
      sel.innerHTML = this.records.map((r, i) =>
        `<option value="${i}">${i + 1}件目：${esc(this.recordTitle(r) || '（氏名未読取）')}</option>`).join('');
      sel.value = String(this.current);
    }

    /** すべての件の元画像を破棄する（画面が抱えているぶん）。 */
    dropAllImages() {
      const total = this.records.reduce(
        (a, r) => a + (this.review ? this.review.imageBytes(r) : 0), 0);
      if (!total) return this.toast('破棄する元画像はありません');
      const mb = (total / 1024 / 1024).toFixed(1);
      if (!confirm(`${this.records.length} 件の元画像（約 ${mb} MB）を画面から破棄します。\n`
        + '読み取った内容はそのまま残りますが、元画像との見比べはできなくなります。\n\n'
        + 'よろしいですか？')) return;
      for (const r of this.records) this.review.dropImages(r);
      this.review.show(this.records[this.current] || null);
      this.renderRecords();
      this.setExportStatus(`元画像（約 ${mb} MB）を破棄しました`);
    }

    renderRecords() {
      const tbody = document.querySelector('#records-table tbody');
      // 画面が抱えている元画像の量を出す（破棄できるように）
      const drop = document.getElementById('btn-drop-all-images');
      if (drop) {
        const total = this.records.reduce(
          (a, r) => a + (this.review ? this.review.imageBytes(r) : 0), 0);
        drop.hidden = !total;
        drop.textContent = `すべての元画像を破棄（約 ${(total / 1024 / 1024).toFixed(1)} MB）`;
      }
      if (!this.records.length) {
        tbody.innerHTML = '<tr><td colspan="7" class="muted">まだ読み取り結果がありません。</td></tr>';
        return;
      }
      tbody.innerHTML = this.records.map((r, i) => {
        let low = 0, edited = 0;
        for (const id of this.schema.order) {
          const e = r.fields[id]; if (!e) continue;
          if (e.edited) edited++;
          else if (e.level === 'low' || e.level === 'medium') low++;
        }
        const srcs = [...new Set(r.pages.map(p => p.source))].join('、');
        return `<tr>
          <td>${i + 1}</td>
          <td>${esc(this.recordTitle(r) || '（未読取）')}</td>
          <td class="muted">${esc(r.templateId || '-')}</td>
          <td class="muted">${esc(srcs)}</td>
          <td>${low ? `<span class="conf low"><span class="dot"></span>${low}</span>` :
                      '<span class="conf high"><span class="dot"></span>0</span>'}</td>
          <td>${edited ? `<span class="conf edited"><span class="dot"></span>${edited}</span>` : '-'}</td>
          <td style="text-align:right">
            <button class="btn sm" data-open="${i}">開く</button>
            <button class="btn sm" data-del="${i}">削除</button></td>
        </tr>`;
      }).join('');
      tbody.querySelectorAll('button[data-open]').forEach(b => b.addEventListener('click', () => {
        this.current = +b.dataset.open;
        this.refreshRecordSelect();
        this.review.show(this.records[this.current]);
        this.showView('review');
      }));
      tbody.querySelectorAll('button[data-del]').forEach(b => b.addEventListener('click', () => {
        if (!confirm('この1件を削除します。よろしいですか？')) return;
        this.records.splice(+b.dataset.del, 1);
        this.current = Math.max(0, Math.min(this.current, this.records.length - 1));
        this.persist(); this.refreshRecordSelect(); this.renderRecords();
        this.review.show(this.records[this.current] || null);
      }));
    }

    exportAll(kind) {
      if (!this.records.length) return this.setExportStatus('出力する件がありません', true);
      if (global.IkenshoOpLog) global.IkenshoOpLog.flush();   // 打ちかけの修正も記録に残す
      this.op('export', { count: this.records.length, note: kind.toUpperCase() });

      const E = global.IkenshoExport;
      if (kind === 'json') E.exportJson(this.records, this.schema);
      else if (kind === 'form') E.exportFormJson(this.records, this.schema);
      else E.exportCsv(this.records, this.schema);
      const name = { json: 'JSON', form: '様式の形のJSON', csv: 'CSV' }[kind] || kind;
      this.setExportStatus(`${this.records.length} 件を${name}で保存しました`);
    }

    async importJson(ev) {
      const file = ev.target.files[0];
      if (!file) return;
      try {
        const payload = JSON.parse(await file.text());
        const recs = global.IkenshoExport.importJson(payload, this.schema);
        this.records = this.records.concat(recs);
        this.persist(); this.refreshRecordSelect(); this.renderRecords();
        this.op('import', { count: recs.length });
        this.setExportStatus(`${recs.length} 件を読み込みました`);
      } catch (e) {
        this.setExportStatus('読み込みに失敗しました: ' + e.message, true);
      }
      ev.target.value = '';
    }

    setExportStatus(msg, isError) {
      const el = document.getElementById('export-status');
      el.textContent = msg;
      el.className = 'status' + (isError ? ' err' : '');
    }
  }

  /** 例外の文面に混ざったファイル名（氏名を含むことがある）を伏せる。 */
  function scrubNames(msg) {
    return String(msg || '').replace(/[^\s、,]+\.(pdf|jpe?g|png|json|csv)/gi, '（ファイル名）');
  }

  function readJson(key) {
    try { return JSON.parse(localStorage.getItem(key) || 'null'); }
    catch (e) { return null; }
  }

  document.addEventListener('DOMContentLoaded', () => {
    global.app = new App();
    global.app.start();
  });
})(window);
