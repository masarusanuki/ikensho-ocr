/**
 * 管理画面。
 * システム情報の確認、様式テンプレートの編集、医療辞書の編集、しきい値の調整。
 */
(function (global) {
  'use strict';
  const esc = s => String(s).replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  const THRESHOLDS = [
    { key: 'EMPTY_MAX', label: 'チェック無しと判定する上限', hint: '枠内のインク率がこれ未満なら未チェック', min: 0.02, max: 0.25, step: 0.01 },
    { key: 'FILLED_MIN', label: 'チェック有りと判定する下限', hint: '枠内のインク率がこれ以上ならチェック済み', min: 0.12, max: 0.60, step: 0.01 },
    { key: 'CONF_HIGH', label: '確信度「高」の下限', hint: '緑で表示する境目', min: 0.5, max: 0.99, step: 0.01 },
    { key: 'CONF_MID', label: '確信度「中」の下限', hint: 'これ未満は赤（要入力）', min: 0.1, max: 0.9, step: 0.01 },
    { key: 'MIN_INLIERS', label: '様式判定に必要な対応点数', hint: '少なすぎる場合は判別失敗とする', min: 8, max: 120, step: 1 },
  ];
  const DEFAULTS = { EMPTY_MAX: 0.10, FILLED_MIN: 0.28, CONF_HIGH: 0.80, CONF_MID: 0.50, MIN_INLIERS: 25 };

  class Admin {
    constructor(app) {
      this.app = app;
      this.tplId = null;
      this.tplPage = 1;
      this.selectedField = null;
      this.drag = null;
      this.dictKey = null;
      this.bind();
    }

    bind() {
      document.getElementById('tpl-select').addEventListener('change', e => {
        this.tplId = e.target.value; this.tplPage = 1; this.renderTemplate();
      });
      document.getElementById('tpl-page').addEventListener('change', e => {
        this.tplPage = +e.target.value; this.renderTemplate();
      });
      document.getElementById('tpl-filter').addEventListener('input', () => this.renderTplFields());
      document.getElementById('btn-tpl-export').addEventListener('click', () => this.exportTemplate());
      document.getElementById('btn-tpl-import').addEventListener('click',
        () => document.getElementById('tpl-import-input').click());
      document.getElementById('tpl-import-input').addEventListener('change', e => this.importTemplate(e));

      document.getElementById('dict-select').addEventListener('change', e => {
        this.dictKey = e.target.value; this.renderDict();
      });
      document.getElementById('dict-filter').addEventListener('input', () => this.renderDict());
      document.getElementById('btn-dict-add').addEventListener('click', () => this.addDictEntry());
      document.getElementById('btn-dict-export').addEventListener('click', () => this.exportDict());
      document.getElementById('btn-dict-import').addEventListener('click',
        () => document.getElementById('dict-import-input').click());
      document.getElementById('dict-import-input').addEventListener('change', e => this.importDict(e));

      document.getElementById('btn-thresh-reset').addEventListener('click', () => {
        Object.assign(this.app.settings, DEFAULTS);
        this.app.saveSettings(); this.renderThresholds();
      });

      // 利用者のトークン（保存先を人ごとに分ける）
      document.getElementById('btn-token-copy').addEventListener('click', () => this.copyToken());
      document.getElementById('btn-token-new').addEventListener('click', () => this.newToken());
      document.getElementById('btn-token-use').addEventListener('click', () => this.useToken());
      document.getElementById('btn-token-purge').addEventListener('click', () => this.purgeOthers());
      document.getElementById('btn-hosp-update').addEventListener('click',
        () => this.updateHospitals());

      // 操作ログ
      document.getElementById('oplog-values').addEventListener('change', e => {
        global.IkenshoOpLog.keepValues = e.target.checked;
        this.app.toast(e.target.checked
          ? '以後の操作は値も記録します' : '以後の操作は値を記録しません（文字数のみ）');
      });
      document.getElementById('btn-oplog-json').addEventListener('click', () => {
        global.IkenshoOpLog.flush();
        global.IkenshoExport.download(`ikensho_oplog_${global.IkenshoSession.short()}.json`,
          global.IkenshoOpLog.toJson(), 'application/json;charset=utf-8');
        this.renderOpLog();
      });
      document.getElementById('btn-oplog-csv').addEventListener('click', () => {
        global.IkenshoOpLog.flush();
        global.IkenshoExport.download(`ikensho_oplog_${global.IkenshoSession.short()}.csv`,
          global.IkenshoOpLog.toCsv(), 'text/csv;charset=utf-8');
        this.renderOpLog();
      });
      document.getElementById('btn-oplog-clear').addEventListener('click', () => {
        if (!confirm('この利用者（今のトークン）の操作ログを消します。元に戻せません。よろしいですか？')) return;
        global.IkenshoOpLog.clear();
        this.renderOpLog();
        this.app.toast('操作ログを消去しました');
      });

      const canvas = document.getElementById('tpl-canvas');
      canvas.addEventListener('pointerdown', e => this.onDown(e));
      canvas.addEventListener('pointermove', e => this.onMove(e));
      window.addEventListener('pointerup', () => this.onUp());
    }

    // -------------------------------------------------------------- 初期化
    render() {
      this.renderSysInfo();
      this.renderModels();
      const tplSel = document.getElementById('tpl-select');
      const ids = Object.keys(this.app.pipeline.templates);
      tplSel.innerHTML = ids.map(id =>
        `<option value="${esc(id)}">${esc(this.app.pipeline.templates[id].name)}</option>`).join('');
      this.tplId = this.tplId && ids.includes(this.tplId) ? this.tplId : ids[0];
      tplSel.value = this.tplId;

      const dictSel = document.getElementById('dict-select');
      const dicts = this.app.pipeline.dicts.lexicons;
      const keys = Object.keys(dicts).filter(k => k !== 'boilerplate');
      dictSel.innerHTML = keys.map(k =>
        `<option value="${esc(k)}">${esc(dicts[k].label)}（${dicts[k].entries.length}件）</option>`).join('');
      this.dictKey = this.dictKey && keys.includes(this.dictKey) ? this.dictKey : keys[0];
      dictSel.value = this.dictKey;

      this.renderTemplate();
      this.renderDict();
      this.renderThresholds();
      this.renderToken();
      this.renderOpLog();
      this.renderHospitals();
    }

    // ------------------------------------------------------ 医療機関一覧
    /**
     * 医療機関一覧の状況と「最新版に更新」。
     * 取得はサーバ側で行うため、`ikensho serve` で開いた場合だけ出す。
     */
    async renderHospitals() {
      const panel = document.getElementById('panel-hospitals');
      let info;
      try {
        const res = await fetch('api/hospitals');
        if (!res.ok) throw new Error(String(res.status));
        info = await res.json();
      } catch (e) {
        panel.hidden = true;              // 静的配信では更新できない
        return;
      }
      panel.hidden = false;
      this.hospInfo = info;

      const dl = document.getElementById('hosp-info');
      dl.innerHTML = [
        ['収録', `${info.prefectures} / 47 都道府県`],
        ['件数', `${(info.total || 0).toLocaleString()} 件`],
        ['基準日', info.as_of || '（不明）'],
        ['取得元', `厚生労働省 地方厚生局（${(info.bureaus || []).join('・')}）`],
      ].map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join('');
      document.getElementById('hosp-updated').textContent =
        info.updated ? `最終取得 ${info.updated.slice(0, 16).replace('T', ' ')}` : '';

      const tb = document.querySelector('#hosp-table tbody');
      const items = info.items || [];
      tb.innerHTML = items.length
        ? items.map(x => `<tr><td>${esc(x.pref)}</td>` +
            `<td style="text-align:right">${(x.count || 0).toLocaleString()}</td>` +
            `<td style="white-space:nowrap">${esc(x.as_of || '')}</td></tr>`).join('')
        : '<tr><td class="hint">まだ取得していません</td></tr>';

      const p = info.progress || {};
      if (p.status === 'running') this.watchHospitals();
      else if (p.status === 'error') this.setHospMsg(p.message, true);
    }

    setHospMsg(text, isError) {
      const box = document.getElementById('hosp-progress');
      const msg = document.getElementById('hosp-msg');
      box.hidden = false;
      msg.textContent = text || '';
      msg.className = 'status' + (isError ? ' err' : '');
    }

    async updateHospitals() {
      const btn = document.getElementById('btn-hosp-update');
      if (!confirm('厚生労働省から医療機関一覧を取り直します。\n'
        + '十数分かかります。その間もほかの操作はできます。\n\n続けますか？')) return;
      btn.disabled = true;
      btn.textContent = '取得中…';
      try {
        const res = await fetch('api/hospitals/update', { method: 'POST' });
        const r = await res.json();
        if (r.error) throw new Error(r.error);
        this.setHospMsg('取得を始めました…');
        this.watchHospitals();
      } catch (e) {
        btn.disabled = false;
        btn.textContent = '最新版に更新';
        this.app.toast('取得を開始できませんでした: ' + e.message, true);
      }
    }

    watchHospitals() {
      const btn = document.getElementById('btn-hosp-update');
      const bar = document.getElementById('hosp-bar');
      btn.disabled = true;
      btn.textContent = '取得中…';
      clearInterval(this._hospTimer);
      this._hospTimer = setInterval(async () => {
        let info;
        try { info = await fetch('api/hospitals').then(r => r.json()); }
        catch (e) { return; }
        const p = info.progress || {};
        bar.value = p.prefs || 0;
        this.setHospMsg(
          `${p.prefs || 0} / 47 都道府県　${(p.total || 0).toLocaleString()} 件`
          + (p.message ? `　${p.message}` : ''),
          p.status === 'error');
        if (p.status === 'running') return;
        clearInterval(this._hospTimer);
        btn.disabled = false;
        btn.textContent = '最新版に更新';
        if (p.status === 'done') {
          // 確認画面が持っている読み込み済みの一覧を捨てて、新しいものを使う
          if (this.app.review) this.app.review._hospIndex = null;
          this.app.toast(p.message || '医療機関一覧を更新しました');
        }
        this.renderHospitals();
      }, 2000);
    }

    // ------------------------------------------------------ 利用者トークン
    renderToken() {
      const S = global.IkenshoSession;
      document.getElementById('token-view').textContent = S.token;
      const others = S.otherCount();
      const btn = document.getElementById('btn-token-purge');
      if (btn) {
        btn.hidden = others === 0;
        btn.textContent = `この端末に残っている他の記録を消す（${others}件）`;
      }
      if (!S.storable) {
        return this.setTokenStatus(
          'この環境ではブラウザに保存できません（読み取り結果も操作ログも残りません）。'
          + 'ファイルを直接開いている場合は、サーバ経由で開いてください。', true);
      }
      this.setTokenStatus(others > 0
        ? `この端末には、ほかに ${others} 件ぶんの記録が残っています。`
          + '見えないだけで消えてはいないので、共用端末では作業後に消してください'
        : 'この端末の記録はこのトークンの分だけです');
    }

    /** 共用端末で作業を終えるとき、他の利用者の記録を実際に消す。 */
    purgeOthers() {
      const n = global.IkenshoSession.otherCount();
      if (!n) return;
      if (!confirm(`この端末に残っている他の ${n} 件ぶんの記録（読み取り結果・操作ログ）を消します。\n`
        + '元に戻せません。よろしいですか？')) return;
      const removed = global.IkenshoSession.clearOthers();
      this.renderToken();
      this.app.toast(`${removed} 件の保存領域を消しました`);
    }

    setTokenStatus(msg, isError) {
      const el = document.getElementById('token-status');
      el.textContent = msg;
      el.className = 'status' + (isError ? ' err' : '');
    }

    async copyToken() {
      const t = global.IkenshoSession.token;
      try {
        await navigator.clipboard.writeText(t);
        this.setTokenStatus('トークンをコピーしました');
      } catch (e) {
        this.setTokenStatus('コピーできませんでした。手で控えてください: ' + t, true);
      }
    }

    newToken() {
      if (!confirm('新しいトークンを発行します。\n'
        + '今の読み取り結果と操作ログは、この画面からは見えなくなります。\n'
        + '（消えるわけではなく、元のトークンを入れ直せば戻せます）\n\n'
        + '今のトークン: ' + global.IkenshoSession.token)) return;
      global.IkenshoSession.reissue();
      location.reload();
    }

    useToken() {
      const v = document.getElementById('token-input').value;
      try {
        global.IkenshoSession.use(v);
      } catch (e) {
        return this.setTokenStatus(e.message, true);
      }
      location.reload();
    }

    // ---------------------------------------------------------- 操作ログ
    renderOpLog() {
      const L = global.IkenshoOpLog;
      document.getElementById('oplog-values').checked = L.keepValues;

      const s = L.summary();
      const dl = document.getElementById('oplog-summary');
      const top = s.よく直した項目.map(([name, n]) => `${esc(name)}（${n}）`).join('、') || 'なし';
      dl.innerHTML = [
        ['記録件数', `${s.件数} 件`],
        ['読み取った件数', `${s.読み取り} 件`],
        ['修正した項目', `${s.修正} 回`],
        ['確定した項目', `${s.確定} 件`],
        ['削除して確定', `${s.削除して確定} 件`],
        ['候補から採用', `${s.候補採用} 回`],
        ['音声入力', `${s.音声入力} 回`],
        ['書き出し', `${s.書き出し} 回`],
        ['直した文字数（合計）', `${s.文字の増減} 文字`],
        ['よく直した項目', top],
      ].map(([k, v]) => `<dt>${esc(k)}</dt><dd>${v === top ? v : esc(v)}</dd>`).join('');

      const tb = document.querySelector('#oplog-table tbody');
      const rows = L.entries.slice(-200).reverse();
      if (!rows.length) {
        tb.innerHTML = '<tr><td class="hint">まだ記録がありません</td></tr>';
        return;
      }
      tb.innerHTML = rows.map(e => {
        const when = e.t.slice(0, 19).replace('T', ' ');
        const what = [e.label || e.field || '', e.note || ''].filter(Boolean).join(' / ');
        const diff = (e.before || e.after)
          ? `${esc(e.before || '（空）')} → ${esc(e.after || '（空）')}` : '';
        return `<tr><td style="white-space:nowrap">${esc(when)}</td>` +
          `<td style="white-space:nowrap">${esc(L.label(e.action))}</td>` +
          `<td>${esc(what)}${e.count ? `（${e.count}件）` : ''}</td>` +
          `<td>${diff}</td></tr>`;
      }).join('');
    }

    /**
     * LLMモデルの一覧と取得。
     * サーバ版（ikensho serve）でのみ使える。ブラウザだけで開いた場合は
     * ファイルを保存できないので、そもそもパネルを出さない。
     */
    async renderModels() {
      const panel = document.getElementById('panel-models');
      let info;
      try {
        const res = await fetch('api/models');
        if (!res.ok) throw new Error(String(res.status));
        info = await res.json();
      } catch (e) {
        panel.hidden = true;
        return;
      }
      panel.hidden = false;

      const state = document.getElementById('model-state');
      if (!info.runtime) {
        state.innerHTML = '実行環境が入っていません。次を実行してください：' +
          '<code class="inline">pip install --extra-index-url ' +
          'https://abetlen.github.io/llama-cpp-python/whl/cpu llama-cpp-python</code>';
      } else if (info.enabled) {
        state.innerHTML = `<span class="conf high"><span class="dot"></span>有効</span> ` +
          `使用中: <code class="inline">${esc(info.current)}</code>`;
      } else {
        state.textContent = 'モデルが置かれていません。下から選んで取得してください。';
      }

      const list = document.getElementById('model-list');
      list.innerHTML = info.models.map(m => `
        <div class="modelcard${m.installed ? ' on' : ''}">
          <div class="mname">${esc(m.key)}</div>
          <div class="mnote">${esc(m.note)}</div>
          <div class="mfoot">
            ${m.installed
              ? '<span class="conf high"><span class="dot"></span>取得済み</span>'
              : `<button class="btn sm primary" data-get="${esc(m.key)}">ダウンロード</button>`}
            ${m.installed && info.current === m.file
              ? '<span class="muted" style="font-size:12px">使用中</span>' : ''}
          </div>
        </div>`).join('');
      list.querySelectorAll('button[data-get]').forEach(b => {
        b.addEventListener('click', () => this.downloadModel(b.dataset.get, b));
      });

      if (info.progress && info.progress.status === 'running') this.watchDownload();
    }

    async downloadModel(key, btn) {
      btn.disabled = true;
      btn.textContent = '取得中…';
      try {
        const res = await fetch('api/models/download', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ key }),
        });
        const r = await res.json();
        if (r.error) throw new Error(r.error);
        this.watchDownload();
      } catch (e) {
        btn.disabled = false;
        btn.textContent = 'ダウンロード';
        this.app.toast('取得を開始できませんでした: ' + e.message, true);
      }
    }

    watchDownload() {
      const box = document.getElementById('model-progress');
      const bar = document.getElementById('model-bar');
      const msg = document.getElementById('model-msg');
      box.hidden = false;
      clearInterval(this._dlTimer);
      this._dlTimer = setInterval(async () => {
        let info;
        try { info = await fetch('api/models').then(r => r.json()); }
        catch (e) { return; }
        const p = info.progress || {};
        const mb = n => (n / 1024 / 1024).toFixed(0);
        if (p.total) {
          bar.value = Math.min(100, p.received / p.total * 100);
          msg.textContent = `${esc(p.name)} を取得しています… ${mb(p.received)} / ${mb(p.total)} MB`;
        } else {
          msg.textContent = `${esc(p.name)} を取得しています…`;
        }
        if (p.status === 'done' || p.status === 'error') {
          clearInterval(this._dlTimer);
          bar.value = p.status === 'done' ? 100 : 0;
          msg.textContent = p.message || '';
          msg.className = 'status' + (p.status === 'error' ? ' err' : '');
          setTimeout(() => { box.hidden = true; this.renderModels(); }, 2500);
        }
      }, 1000);
    }

    renderSysInfo() {
      const p = this.app.pipeline;
      const nBox = Object.values(p.templates).reduce(
        (a, t) => a + t.pages.reduce((b, pg) => b + pg.boxes.length, 0), 0);
      const nText = Object.values(p.templates).reduce(
        (a, t) => a + t.pages.reduce((b, pg) => b + pg.texts.length, 0), 0);
      document.getElementById('sysinfo').innerHTML = `
        <dt>様式</dt><dd>${esc(p.schema.formName)}</dd>
        <dt>項目定義</dt><dd>v${esc(p.schema.version)}／${p.schema.order.length} 項目</dd>
        <dt>テンプレート</dt><dd>${Object.keys(p.templates).length} 種類</dd>
        <dt>チェックボックス</dt><dd>${nBox} 個（全様式合計）</dd>
        <dt>テキスト欄</dt><dd>${nText} 個（全様式合計）</dd>
        <dt>読み取り済み</dt><dd>${this.app.records.length} 件</dd>`;
      document.getElementById('libinfo').innerHTML = `
        <dt>実行場所</dt><dd>ブラウザ内（データは外部送信なし）</dd>
        <dt>画像処理</dt><dd>OpenCV.js ${global.cv && cv.getBuildInformation ? '読込済' : '未読込'}</dd>
        <dt>PDF描画</dt><dd>${global.pdfjsLib ? 'pdf.js 読込済' : '未読込'}</dd>
        <dt>OCR</dt><dd>${this.app.pipeline.ocrReady ? 'tesseract.js（日本語）' : '未初期化'}</dd>
        <dt>保存先</dt><dd>この端末のブラウザ内（localStorage）</dd>`;
    }

    // ------------------------------------------------------ テンプレート編集
    renderTemplate() {
      const tpl = this.app.pipeline.templates[this.tplId];
      if (!tpl) return;
      const pageSel = document.getElementById('tpl-page');
      pageSel.innerHTML = tpl.pages.map(p =>
        `<option value="${p.index}">${p.index}ページ目</option>`).join('');
      pageSel.value = this.tplPage;
      this.drawTemplate();
      this.renderTplFields();
    }

    drawTemplate() {
      const tpl = this.app.pipeline.templates[this.tplId];
      const page = tpl.pages.find(p => p.index === this.tplPage);
      if (!page) return;
      const canvas = document.getElementById('tpl-canvas');
      const img = new Image();
      img.onload = () => {
        canvas.width = img.naturalWidth;
        canvas.height = img.naturalHeight;
        const ctx = canvas.getContext('2d');
        ctx.drawImage(img, 0, 0);
        const W = canvas.width, H = canvas.height;
        ctx.lineWidth = 1.5;
        for (const b of page.boxes) {
          ctx.strokeStyle = (b.field === this.selectedField) ? '#ff9f0a' : 'rgba(200,30,30,.75)';
          ctx.strokeRect(b.rect[0] * W, b.rect[1] * H, b.rect[2] * W, b.rect[3] * H);
        }
        for (const t of page.texts) {
          ctx.strokeStyle = (t.field === this.selectedField) ? '#ff9f0a' : 'rgba(30,90,168,.75)';
          ctx.strokeRect(t.rect[0] * W, t.rect[1] * H, t.rect[2] * W, t.rect[3] * H);
        }
      };
      img.src = (global.IkenshoResolveUrl || (u => u))(
        `${this.app.pipeline.base}/templates/refs/${page.ref}`);
      this._pageRef = page;
    }

    renderTplFields() {
      const tpl = this.app.pipeline.templates[this.tplId];
      const page = tpl.pages.find(p => p.index === this.tplPage);
      const q = document.getElementById('tpl-filter').value.trim();
      const schema = this.app.pipeline.schema;
      const rows = [];
      const seen = new Set();
      for (const t of page.texts) {
        const f = schema.byId[t.field];
        if (!f || (q && !f.label.includes(q) && !t.field.includes(q))) continue;
        rows.push({ id: t.field, label: f.label, kind: 'テキスト欄', rect: t.rect });
        seen.add(t.field);
      }
      for (const b of page.boxes) {
        if (seen.has(b.field)) continue;
        const f = schema.byId[b.field];
        if (!f || (q && !f.label.includes(q) && !b.field.includes(q))) continue;
        seen.add(b.field);
        rows.push({ id: b.field, label: f.label, kind: 'チェック', rect: null });
      }
      const tbody = document.querySelector('#tpl-fields tbody');
      tbody.innerHTML = rows.map(r => `
        <tr data-field="${esc(r.id)}" class="${r.id === this.selectedField ? 'sel' : ''}">
          <td>${esc(r.label)}</td>
          <td class="muted" style="white-space:nowrap">${r.kind}</td>
        </tr>`).join('');
      tbody.querySelectorAll('tr').forEach(tr => {
        tr.addEventListener('click', () => {
          this.selectedField = tr.dataset.field;
          this.renderTplFields();
          this.drawTemplate();
        });
      });
    }

    canvasPos(e) {
      const c = document.getElementById('tpl-canvas');
      const r = c.getBoundingClientRect();
      return { x: (e.clientX - r.left) / r.width, y: (e.clientY - r.top) / r.height };
    }

    onDown(e) {
      if (!this.selectedField) return;
      const page = this._pageRef;
      const t = page.texts.find(t => t.field === this.selectedField);
      if (!t) return;   // チェックボックスの一括移動は行わない
      this.drag = Object.assign({ target: t }, this.canvasPos(e));
      e.preventDefault();
    }

    onMove(e) {
      if (!this.drag) return;
      const p = this.canvasPos(e);
      const x0 = Math.min(this.drag.x, p.x), y0 = Math.min(this.drag.y, p.y);
      const w = Math.abs(p.x - this.drag.x), h = Math.abs(p.y - this.drag.y);
      if (w < 0.004 || h < 0.002) return;
      this.drag.target.rect = [round6(x0), round6(y0), round6(w), round6(h)];
      this.drag.target.edited = true;
      this.drawTemplate();
    }

    onUp() {
      if (this.drag) { this.drag = null; this.app.toast('テンプレートを更新しました（書き出して保存してください）'); }
    }

    exportTemplate() {
      const tpl = this.app.pipeline.templates[this.tplId];
      global.IkenshoExport.download(`${this.tplId}.json`,
        JSON.stringify(tpl, null, 1), 'application/json;charset=utf-8');
    }

    async importTemplate(ev) {
      const file = ev.target.files[0];
      if (!file) return;
      try {
        const raw = JSON.parse(await file.text());
        if (!raw.id || !raw.pages) throw new Error('テンプレートの形式が正しくありません');
        this.app.pipeline.templates[raw.id] = raw;
        await this.app.pipeline.loadTemplateRefs(raw);
        this.tplId = raw.id;
        this.render();
        this.app.toast(`様式「${raw.name || raw.id}」を読み込みました`);
      } catch (e) {
        this.app.toast('読み込みに失敗しました: ' + e.message, true);
      }
      ev.target.value = '';
    }

    // ---------------------------------------------------------- 辞書編集
    renderDict() {
      const lex = this.app.pipeline.dicts.lexicons[this.dictKey];
      if (!lex) return;
      const q = document.getElementById('dict-filter').value.trim();
      const rows = lex.entries
        .map((e, i) => ({ e, i }))
        .filter(({ e }) => !q || e.name.includes(q) || (e.icd10 || '').includes(q))
        .slice(0, 400);
      const tbody = document.querySelector('#dict-table tbody');
      tbody.innerHTML = rows.map(({ e, i }) => `
        <tr>
          <td>${esc(e.name)}</td>
          <td class="muted" style="white-space:nowrap">${esc(e.icd10 || '')}</td>
          <td style="white-space:nowrap">${e.tokutei ? '<span class="conf medium">特定疾病</span>' : ''}</td>
          <td style="text-align:right"><button class="btn sm" data-i="${i}">削除</button></td>
        </tr>`).join('');
      tbody.querySelectorAll('button[data-i]').forEach(b => {
        b.addEventListener('click', () => {
          lex.entries.splice(+b.dataset.i, 1);
          this.renderDict();
        });
      });
    }

    addDictEntry() {
      const lex = this.app.pipeline.dicts.lexicons[this.dictKey];
      const name = prompt('追加する語句');
      if (!name) return;
      const entry = { name: name.trim() };
      if (this.dictKey === 'diseases') {
        const icd = prompt('ICD-10コード（任意）') || '';
        if (icd.trim()) entry.icd10 = icd.trim();
        entry.tokutei = confirm('介護保険の特定疾病として扱いますか？');
      }
      lex.entries.unshift(entry);
      this.renderDict();
      this.app.toast('辞書に追加しました（書き出して保存してください）');
    }

    exportDict() {
      const lex = this.app.pipeline.dicts.lexicons[this.dictKey];
      global.IkenshoExport.download(`${this.dictKey}.json`,
        JSON.stringify({ label: lex.label, entries: lex.entries }, null, 1),
        'application/json;charset=utf-8');
    }

    async importDict(ev) {
      const file = ev.target.files[0];
      if (!file) return;
      try {
        const raw = JSON.parse(await file.text());
        if (!Array.isArray(raw.entries)) throw new Error('辞書の形式が正しくありません');
        const key = file.name.replace(/\.json$/i, '');
        this.app.pipeline.dicts.lexicons[key] =
          { key, label: raw.label || key, entries: raw.entries };
        this.dictKey = key;
        this.render();
        this.app.toast(`辞書「${raw.label || key}」を読み込みました（${raw.entries.length}件）`);
      } catch (e) {
        this.app.toast('読み込みに失敗しました: ' + e.message, true);
      }
      ev.target.value = '';
    }

    // -------------------------------------------------------- しきい値調整
    renderThresholds() {
      const host = document.getElementById('thresholds');
      host.innerHTML = '';
      for (const t of THRESHOLDS) {
        const v = this.app.settings[t.key];
        const box = document.createElement('div');
        box.innerHTML = `
          <label style="font-size:12.5px;font-weight:600">${esc(t.label)}</label>
          <div class="row" style="gap:8px;margin-top:4px">
            <input type="range" min="${t.min}" max="${t.max}" step="${t.step}" value="${v}" style="flex:1">
            <output style="min-width:46px;text-align:right;font-variant-numeric:tabular-nums">${v}</output>
          </div>
          <div class="hint" style="margin:2px 0 0">${esc(t.hint)}</div>`;
        const range = box.querySelector('input');
        const out = box.querySelector('output');
        range.addEventListener('input', () => {
          out.textContent = range.value;
          this.app.settings[t.key] = +range.value;
          this.app.saveSettings();
        });
        host.appendChild(box);
      }
    }
  }

  function round6(n) { return Math.round(n * 1e6) / 1e6; }

  global.IkenshoAdmin = Admin;
})(window);
