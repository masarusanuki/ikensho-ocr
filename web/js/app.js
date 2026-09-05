/** アプリ全体の制御。画面切り替え、ファイル受け取り、読み取り実行、保存。 */
(function (global) {
  'use strict';
  const esc = s => global.IkenshoUtil.esc(s);
  const STORAGE_KEY = 'ikensho.records.v1';
  const SETTINGS_KEY = 'ikensho.settings.v1';
  const DEFAULT_SETTINGS = { EMPTY_MAX: 0.10, FILLED_MIN: 0.28, CONF_HIGH: 0.80, CONF_MID: 0.50, MIN_INLIERS: 25 };

  class App {
    constructor() {
      this.files = [];
      this.records = [];
      this.current = 0;
      this.settings = Object.assign({}, DEFAULT_SETTINGS, readJson(SETTINGS_KEY) || {});
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
      this.review = new global.IkenshoReview(this);
      this.admin = new global.IkenshoAdmin(this);
      this.restore();
      this.setStatus('準備ができました。ファイルを読み込んでください。');
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
      document.getElementById('btn-export-json-one').addEventListener('click', () => {
        const r = this.records[this.current];
        if (!r) return this.toast('出力する件がありません', true);
        global.IkenshoExport.exportJson([r], this.schema,
          `ikensho_${this.recordTitle(r) || 'record'}.json`);
      });
      document.getElementById('btn-import').addEventListener('click',
        () => document.getElementById('import-input').click());
      document.getElementById('import-input').addEventListener('change', e => this.importJson(e));
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

    // ------------------------------------------------------------ 実行
    async run() {
      const btn = document.getElementById('btn-run');
      const prog = document.getElementById('prog');
      btn.disabled = true; prog.hidden = false; prog.value = 0;
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
        this.showView('review');
      } catch (e) {
        console.error(e);
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
        localStorage.setItem(STORAGE_KEY, JSON.stringify(slim));
      } catch (e) { /* 容量超過時は保存しない */ }
    }

    restore() {
      const saved = readJson(STORAGE_KEY);
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
      localStorage.setItem(SETTINGS_KEY, JSON.stringify(this.settings));
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

    renderRecords() {
      const tbody = document.querySelector('#records-table tbody');
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
      if (kind === 'json') global.IkenshoExport.exportJson(this.records, this.schema);
      else global.IkenshoExport.exportCsv(this.records, this.schema);
      this.setExportStatus(`${this.records.length} 件を${kind === 'json' ? 'JSON' : 'CSV'}で保存しました`);
    }

    async importJson(ev) {
      const file = ev.target.files[0];
      if (!file) return;
      try {
        const payload = JSON.parse(await file.text());
        const recs = global.IkenshoExport.importJson(payload, this.schema);
        this.records = this.records.concat(recs);
        this.persist(); this.refreshRecordSelect(); this.renderRecords();
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

  function readJson(key) {
    try { return JSON.parse(localStorage.getItem(key) || 'null'); }
    catch (e) { return null; }
  }

  document.addEventListener('DOMContentLoaded', () => {
    global.app = new App();
    global.app.start();
  });
})(window);
