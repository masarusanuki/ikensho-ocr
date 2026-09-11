/**
 * 確認・編集画面。
 * 読み取り値・確信度・元画像の切り抜きを並べ、その場で修正できるようにする。
 */
(function (global) {
  'use strict';

  const LEVEL_LABEL = { high: '高', medium: '中', low: '低',
                        edited: '修正', anon: '匿名化', done: '確定' };

  class Review {
    constructor(app) {
      this.app = app;
      this.record = null;
      this.activeField = null;
      this.currentPage = 1;
      // 絞り込み: null（すべて）／'check'（要確認のみ）／確信度の区分名
      this.filter = null;
      this.imgEl = document.getElementById('page-img');
      this.marker = document.getElementById('marker');
      this.zoom = document.getElementById('zoom');
      this.zoomcap = document.getElementById('zoomcap');
      this.zoomHint = document.getElementById('zoomhint');
      this.zoomScale = 1.0;          // 拡大表示の倍率（利用者が変えられる）
      this.fieldsEl = document.getElementById('fields');
      this.warnEl = document.getElementById('warnings');
      this.bind();
    }

    bind() {
      document.querySelectorAll('[data-page]').forEach(b => {
        b.addEventListener('click', () => this.showPage(+b.dataset.page));
      });
      document.getElementById('only-low').addEventListener('change', e => {
        this.setFilter(e.target.checked ? 'check' : null);
      });
      document.querySelectorAll('[data-zoom]').forEach(b => {
        b.addEventListener('click', () => {
          const step = Number(b.dataset.zoom);
          this.zoomScale = Math.max(0.5, Math.min(3.0, this.zoomScale + step * 0.25));
          document.getElementById('zoomlevel').textContent =
            this.zoomScale === 1 ? '標準' : `${Math.round(this.zoomScale * 100)}%`;
          if (this._lastLoc) this.renderZoom(this._lastLoc);
        });
      });
      const vlmBtn = document.getElementById('btn-vlm-field');
      if (vlmBtn) vlmBtn.addEventListener('click', () => this.rereadWithVlm());
      document.getElementById('opt-overlay').addEventListener('change', e => {
        document.getElementById('frame').classList.toggle('plain', !e.target.checked);
      });
      document.getElementById('btn-anon').addEventListener('click', () => this.toggleAnonymize());
      document.getElementById('btn-drop-images').addEventListener('click',
        () => this.confirmDropImages());
      document.getElementById('btn-next-low').addEventListener('click', () => this.jumpLow(1));
      document.getElementById('btn-prev-low').addEventListener('click', () => this.jumpLow(-1));
    }

    // ------------------------------------------------------------ 表示
    show(record) {
      // 前の件で打ちかけの修正を、件が変わる前に確定させる
      if (global.IkenshoOpLog && this.record && this.record !== record) {
        global.IkenshoOpLog.flush();
      }
      this.record = record;
      this.activeField = null;
      document.getElementById('review-empty').hidden = !!record;
      document.getElementById('review-body').hidden = !record;
      if (!record) return;
      const first = Object.keys(record.images || {}).map(Number).sort()[0] || 1;
      this.showPage(first);
      this.renderWarnings();
      this.renderFields();
      this.updateAnonButton();
    }

    /** 画像上に、項目ごとの当たり判定を敷く。クリックで右の該当項目へ移動する。 */
    renderHotspots() {
      const host = document.getElementById('hotspots');
      if (!host) return;
      host.replaceChildren();
      const tpl = this.app.pipeline.templates[this.record.templateId];
      if (!tpl) return;
      const page = tpl.pages.find(p => p.index === this.currentPage);
      if (!page) return;

      const spots = [];
      for (const t of page.texts) spots.push({ field: t.field, rect: t.rect });
      const byField = {};
      for (const b of page.boxes) {
        const r = byField[b.field];
        const [x, y, w, h] = b.rect;
        if (!r) byField[b.field] = [x, y, x + w, y + h];
        else {
          r[0] = Math.min(r[0], x); r[1] = Math.min(r[1], y);
          r[2] = Math.max(r[2], x + w); r[3] = Math.max(r[3], y + h);
        }
      }
      for (const [f, r] of Object.entries(byField)) {
        // ラベル側も押せるよう右に広げる
        spots.push({ field: f, rect: [r[0], r[1], Math.min(1 - r[0], r[2] - r[0] + 0.10),
                                      r[3] - r[1]] });
      }
      // 小さいものを上に重ねる（大きな枠に埋もれないように）
      spots.sort((a, b) => (b.rect[2] * b.rect[3]) - (a.rect[2] * a.rect[3]));
      for (const s of spots) {
        const el = document.createElement('div');
        // 画像側にも右と同じ判定色を付けて、どこが要確認か一目で分かるようにする
        const entry = this.record.fields[s.field];
        el.className = 'hot' + (entry ? ' hv-' + this.levelOf(entry) : '');
        el.style.left = (s.rect[0] * 100) + '%';
        el.style.top = (s.rect[1] * 100) + '%';
        el.style.width = (s.rect[2] * 100) + '%';
        el.style.height = (s.rect[3] * 100) + '%';
        const f = this.app.schema.byId[s.field];
        el.title = f ? f.label : s.field;
        if (entry) {
          const lv = this.levelOf(entry);
          el.title += `（${LEVEL_LABEL[lv] || lv}${
            lv === 'done' || lv === 'anon' ? '' : ' ' + (entry.confidence * 100).toFixed(0) + '%'}）`;
        }
        el.dataset.field = s.field;
        el.addEventListener('click', ev => {
          ev.stopPropagation();
          this.jumpTo(s.field);
        });
        host.appendChild(el);
      }
    }

    /** 指定の項目を右側で表示・選択する。絞り込み中なら解除して探す。 */
    jumpTo(fieldId) {
      let el = this.fieldsEl.querySelector(`.field[data-field="${fieldId}"]`);
      if (!el && this.filter) {
        // 絞り込みで隠れている項目に飛ぶ場合は、絞り込みを解除する
        this.filter = null;
        const chk = document.getElementById('only-low');
        if (chk) chk.checked = false;
        this.renderFields();
        el = this.fieldsEl.querySelector(`.field[data-field="${fieldId}"]`);
      }
      if (el) {
        el.scrollIntoView({ block: 'center', behavior: 'smooth' });
        this.focusField(fieldId, el);
        const input = el.querySelector('input,textarea');
        if (input) setTimeout(() => input.focus({ preventScroll: true }), 320);
      } else {
        this.focusField(fieldId, null);
      }
    }

    showPage(n) {
      this.currentPage = n;
      const src = (this.record.images || {})[n];
      const dropped = this.record.imagesDropped;
      document.getElementById('page-title').textContent = src
        ? `元画像（${n}ページ目）`
        : (dropped ? '元画像は破棄しました（読み取った内容は残っています）'
                   : `${n}ページ目は取り込まれていません`);
      this.imgEl.src = src || '';
      this.imgEl.style.visibility = src ? 'visible' : 'hidden';
      this.marker.hidden = true;
      this.renderHotspots();
      this.updateDropButton();
    }

    renderWarnings() {
      const w = this.record.warnings || [];
      if (!w.length) { this.warnEl.innerHTML = ''; return; }
      this.warnEl.innerHTML =
        `<div class="warnbox"><strong>確認してください</strong><ul>${
          w.map(x => `<li>${esc(x)}</li>`).join('')}</ul></div>`;
    }

    /** この件が抱えている元画像の大きさ（おおよそのバイト数）。 */
    imageBytes(record) {
      const imgs = (record || {}).images || {};
      let n = 0;
      for (const src of Object.values(imgs)) {
        if (typeof src !== 'string') continue;
        // data URL は base64 なので、実体は 3/4 くらい
        n += Math.round((src.length - (src.indexOf(',') + 1)) * 0.75);
      }
      return n;
    }

    /**
     * 画面が抱えている元画像を捨てる。
     *
     * 元画像は**保存はしていない**（ブラウザに残すのは読み取った内容だけ）が、
     * 開いている間はメモリに載っている。他の人がいる場所で画面を離れるときや、
     * 何件も続けて読み取ってメモリが苦しいときに捨てられるようにする。
     * 読み取った内容と確信度・注記はそのまま残る。
     */
    dropImages(record) {
      const target = record || this.record;
      if (!target) return 0;
      const bytes = this.imageBytes(target);
      target.images = {};
      target.imagesDropped = true;
      if (target === this.record) {
        this._lastLoc = null;
        this.zoom.replaceChildren();
        this.zoomcap.textContent = '元画像は破棄されています';
        if (this.zoomHint) this.zoomHint.hidden = true;
        this.marker.hidden = true;
        this.showPage(this.currentPage);
      }
      this.op('drop_images', {
        note: `${(bytes / 1024 / 1024).toFixed(1)} MB を破棄`,
      });
      this.app.touch();
      return bytes;
    }

    /** 「画像を消す」ボタン。 */
    confirmDropImages() {
      if (!this.record) return;
      if (this.record.imagesDropped || !Object.keys(this.record.images || {}).length) {
        return this.app.toast('この件の元画像は、すでに画面上にありません');
      }
      const mb = (this.imageBytes(this.record) / 1024 / 1024).toFixed(1);
      if (!confirm(`この件の元画像（約 ${mb} MB）を画面から破棄します。\n`
        + '読み取った内容・確信度・注記はそのまま残りますが、\n'
        + '元画像との見比べはできなくなります（もう一度読み込めば戻ります）。\n\n'
        + 'よろしいですか？')) return;
      this.dropImages(this.record);
      this.app.toast(`元画像（約 ${mb} MB）を破棄しました`);
      this.updateDropButton();
    }

    /** 「画像を消す」ボタンの見え方を更新する。 */
    updateDropButton() {
      const btn = document.getElementById('btn-drop-images');
      if (!btn) return;
      const bytes = this.record ? this.imageBytes(this.record) : 0;
      btn.disabled = !bytes;
      btn.textContent = bytes
        ? `画像を消す（${(bytes / 1024 / 1024).toFixed(1)} MB）` : '画像を消す';
    }

    /** 操作ログに1件残す。対象の件名は自動で付ける。 */
    op(action, detail) {
      const L = global.IkenshoOpLog;
      if (!L) return;
      L.add(action, Object.assign({ record: L.recordLabel(this.record) }, detail || {}));
    }

    /** 「匿名化加工済みデータ」ボタン。氏名は匿名化済み、住所などはマスク済みにする。 */
    toggleAnonymize() {
      if (!this.record) return;
      const A = global.IkenshoAnonymize;
      if (this.record.anonymized) {
        if (!confirm('匿名化の表示を解除します。元の読み取り値は復元できません。よろしいですか？')) return;
        A.clear(this.record, this.app.schema);
      } else {
        const n = A.apply(this.record, this.app.schema, true);
        this.app.toast(`${n} 項目を匿名化加工済みデータとして扱います`);
      }
      this.op('anonymize', { note: this.record.anonymized ? '適用' : '解除' });
      this.app.touch();
      this.renderFields();
      this.updateAnonButton();
    }

    updateAnonButton() {
      const b = document.getElementById('btn-anon');
      const on = !!(this.record && this.record.anonymized);
      b.textContent = on ? '匿名化を解除' : '匿名化加工済みデータ';
      b.classList.toggle('primary', on);
    }

    stats() {
      const s = { high: 0, medium: 0, low: 0, edited: 0, done: 0, anon: 0,
                  filled: 0, total: 0 };
      for (const id of this.app.schema.order) {
        const e = this.record.fields[id];
        if (!e) continue;
        s.total++;
        const lv = this.levelOf(e);
        if (lv in s) s[lv]++;          // levelOf が 'done' を返すので二重に数えない
        if (!isEmptyValue(e.value)) s.filled++;
      }
      return s;
    }

    /**
     * 上部の集計を貼り替える。
     * 各区分は押すとその区分だけの表示に切り替わる（もう一度押すと解除）。
     */
    updateStats() {
      const st = this.stats();
      const host = this.fieldsEl.querySelector('.statrow');
      if (!host) return;
      const badges = [
        ['done', '確定', st.done], ['high', '高', st.high],
        ['medium', '中', st.medium], ['low', '要確認', st.low],
        ['edited', '修正', st.edited], ['anon', '匿名化', st.anon],
      ].filter(([, , n], i) => n > 0 || i < 5);
      host.innerHTML = `<span>読み取り ${st.filled} / ${st.total} 項目</span>` +
        badges.map(([lv, label, n]) =>
          `<button type="button" class="conf ${lv} filt${this.filter === lv ? ' on' : ''}"` +
          ` data-level="${lv}"${n ? '' : ' disabled'}` +
          ` title="${esc(label)}の項目だけを表示します">` +
          `<span class="dot"></span>${esc(label)} ${n}</button>`).join('') +
        (this.filter
          ? '<button class="btn sm" id="btn-filter-clear">絞り込みを解除</button>'
          : '') +
        '<button class="btn sm" id="btn-confirm-all">表示中をすべて確定</button>';
      host.querySelectorAll('button[data-level]').forEach(b => {
        b.addEventListener('click', () => this.setFilter(
          this.filter === b.dataset.level ? null : b.dataset.level));
      });
      const clear = host.querySelector('#btn-filter-clear');
      if (clear) clear.addEventListener('click', () => this.setFilter(null));
      const all = host.querySelector('#btn-confirm-all');
      if (all) all.addEventListener('click', () => this.confirmAllVisible());
    }

    /** 絞り込みを切り替える。 */
    setFilter(value) {
      this.filter = value || null;
      const chk = document.getElementById('only-low');
      if (chk) chk.checked = (this.filter === 'check');
      this.renderFields();
    }

    /** その項目をいま表示するか。 */
    passes(e) {
      if (!this.filter) return true;
      if (this.filter === 'check') return this.needsCheck(e);
      return this.levelOf(e) === this.filter;
    }

    /** いま表示されている項目をまとめて確定にする。 */
    confirmAllVisible() {
      const ids = [...this.fieldsEl.querySelectorAll('.field')].map(el => el.dataset.field);
      let n = 0;
      for (const id of ids) {
        const e = this.record.fields[id];
        if (e && !e.confirmed) { e.confirmed = true; n++; }
      }
      this.app.toast(`${n} 項目を確定しました`);
      this.op('confirm_visible', { count: n });
      this.app.touch();
      this.renderFields();
    }

    /**
     * 選択肢を、様式の上での並び（行と順序）どおりに返す。
     * 原本と見比べながら直せるよう、画面でも同じ形にする。
     */
    optionRows(f) {
      const tpl = this.app.pipeline.templates[this.record.templateId];
      if (!tpl) return null;
      let boxes = null;
      for (const p of tpl.pages) {
        const bs = p.boxes.filter(b => b.field === f.id);
        if (bs.length) { boxes = bs; break; }
      }
      if (!boxes || boxes.length !== (f.options || []).length) return null;
      const items = boxes.map(b => ({ opt: b.opt, x: b.rect[0], y: b.rect[1],
                                      h: b.rect[3] }));
      items.sort((a, b) => a.y - b.y || a.x - b.x);
      const rows = [];
      let cur = [items[0]];
      for (const it of items.slice(1)) {
        const top = Math.min(...cur.map(c => c.y));
        if (it.y - top > (it.h || 0.01) * 0.8) { rows.push(cur); cur = []; }
        cur.push(it);
      }
      rows.push(cur);
      return rows.map(r => r.sort((a, b) => a.x - b.x).map(i => i.opt));
    }

    /**
     * まとめて扱う項目を1枚のカードにする。
     * 「有無のチェック」と「その内容」のように、様式では一体になっているものを
     * 画面でも一体にして、原本と見比べやすくする。
     */
    groupCard(title, members) {
      const box = document.createElement('div');
      box.className = 'group';
      const head = document.createElement('div');
      head.className = 'grouphead';
      const worst = members.reduce((a, x) => {
        const lv = this.levelOf(this.record.fields[x.id]);
        const rank = { low: 0, medium: 1, edited: 2, high: 3, anon: 4, done: 5 };
        return (rank[lv] < rank[a] ? lv : a);
      }, 'done');
      head.innerHTML = `<span class="gtitle">${esc(title)}</span>` +
        `<span class="conf ${worst}"><span class="dot"></span>${
          LEVEL_LABEL[worst] || worst}</span>`;
      const all = document.createElement('button');
      all.type = 'button';
      all.className = 'confirm';
      all.textContent = 'まとめて確定';
      all.addEventListener('click', ev => {
        ev.stopPropagation();
        for (const m of members) this.record.fields[m.id].confirmed = true;
        this.op('confirm_group', { label: title, count: members.length });
        this.app.touch();
        this.renderFields();
      });
      head.appendChild(all);
      box.appendChild(head);
      for (const m of members) {
        box.appendChild(this.fieldRow(m, this.record.fields[m.id], title));
      }
      return box;
    }

    /** 様式上の位置（ページ→上から下→左から右）を項目ごとに求める。 */
    positionIndex() {
      if (this._posIndex && this._posTpl === this.record.templateId) return this._posIndex;
      const idx = {};
      const tpl = this.app.pipeline.templates[this.record.templateId];
      if (tpl) {
        for (const p of tpl.pages) {
          for (const t of p.texts) {
            const [x, y] = t.rect;
            idx[t.field] = [p.index, y, x];
          }
          const byField = {};
          for (const b of p.boxes) {
            const cur = byField[b.field];
            const [x, y] = b.rect;
            if (!cur || y < cur[1] || (y === cur[1] && x < cur[2])) {
              byField[b.field] = [p.index, y, x];
            }
          }
          for (const [f, v] of Object.entries(byField)) if (!idx[f]) idx[f] = v;
        }
      }
      this._posIndex = idx;
      this._posTpl = this.record.templateId;
      return idx;
    }

    /** 様式上の並び順に項目を並べ替える。 */
    orderedFields(fields) {
      const idx = this.positionIndex();
      const withPos = fields.map((f, i) => ({ f, i, p: idx[f.id] }));
      withPos.sort((a, b) => {
        if (!a.p && !b.p) return a.i - b.i;
        if (!a.p) return 1;
        if (!b.p) return -1;
        return (a.p[0] - b.p[0]) || (a.p[1] - b.p[1]) || (a.p[2] - b.p[2]);
      });
      return withPos.map(w => w.f);
    }

    renderFields() {
      if (!this.record) return;
      (this._dictations || []).forEach(d => d.stop());
      this._dictations = [];
      const schema = this.app.schema;
      const frag = document.createDocumentFragment();

      const st = this.stats();
      let shown = 0;
      const head = document.createElement('div');
      head.className = 'panel statpanel';
      head.style.padding = '9px 14px';
      head.innerHTML = '<div class="row statrow" style="font-size:12.5px"></div>';
      frag.appendChild(head);

      for (const sec of schema.sections) {
        const rows = [];
        const doneGroups = new Set();
        for (const f of this.orderedFields(sec.fields)) {
          const e = this.record.fields[f.id];
          if (!e) continue;
          // 同じグループの項目（有無＋内容など）は1枚にまとめて出す
          if (f.group) {
            if (doneGroups.has(f.group)) continue;
            const members = sec.fields.filter(x => x.group === f.group &&
                                                   this.record.fields[x.id]);
            const visible = members.filter(
              x => this.passes(this.record.fields[x.id]));
            if (!visible.length) { doneGroups.add(f.group); continue; }
            doneGroups.add(f.group);
            rows.push(this.groupCard(f.group_label || f.label, visible));
            continue;
          }
          if (!this.passes(e)) continue;
          rows.push(this.fieldRow(f, e));
        }
        if (!rows.length) continue;
        const box = document.createElement('div');
        box.className = 'fieldsec';
        const h = document.createElement('h3');
        h.textContent = sec.title;
        box.appendChild(h);
        rows.forEach(r => box.appendChild(r));
        frag.appendChild(box);
        shown += rows.length;
      }
      if (!shown && this.filter) {
        const none = document.createElement('div');
        none.className = 'panel';
        none.style.padding = '14px';
        none.innerHTML = '<span class="hint">この区分に当てはまる項目はありません。' +
          '上の区分をもう一度押すと解除できます。</span>';
        frag.appendChild(none);
      }
      this.fieldsEl.replaceChildren(frag);
      this.updateStats();
      this.renderHotspots();
    }

    /**
     * グループの中では、見出しと重なる部分を落として短く出す。
     * 様式の「□褥瘡（部位：　　　　程度：□軽□中□重）」のように、
     * ひとかたまりで書かれているものを画面でも1つに見せる。
     */
    shortLabel(f, groupTitle) {
      if (!groupTitle) return f.label;
      const t = String(groupTitle).trim();
      let s = String(f.label).trim();
      if (s.startsWith(t)) s = s.slice(t.length).trim();
      if (s === f.label.trim()) return f.label;      // 前置きが違う場合はそのまま
      if (!s) return f.type === 'flag' ? '有無' : f.label;
      return s;
    }

    needsCheck(e) {
      if (e.anonymized || e.confirmed) return false;
      return !e.edited && (e.level === 'low' || e.level === 'medium');
    }

    // ------------------------------------------------------- 1項目の描画
    /** その項目をどう表示するか（確定 > 匿名化 > 修正 > 確信度）。 */
    levelOf(e) {
      if (e.confirmed) return 'done';
      if (e.anonymized) return 'anon';
      if (e.edited) return 'edited';
      return e.level;
    }

    fieldRow(f, e, groupTitle) {
      const el = document.createElement('div');
      const level = this.levelOf(e);
      el.className = `field lv-${level}`;
      el.dataset.field = f.id;

      const head = document.createElement('div');
      head.className = 'head';
      const badge = (level === 'anon' || level === 'done')
        ? `<span class="conf ${level}"><span class="dot"></span>${LEVEL_LABEL[level]}</span>`
        : `<span class="conf ${level}"><span class="dot"></span>${LEVEL_LABEL[level]} ${
             (e.confidence * 100).toFixed(0)}%</span>`;
      head.innerHTML = `<span class="lbl">${esc(this.shortLabel(f, groupTitle))}</span>${badge}`;

      // 内容を見て問題なければ「確定」にする。確認済みかどうかが一目で分かる。
      const check = document.createElement('button');
      check.type = 'button';
      check.className = 'confirm' + (e.confirmed ? ' on' : '');
      check.textContent = e.confirmed ? '確定済み' : '確定';
      check.title = e.confirmed ? 'クリックで確定を解除します'
                                : '内容を確認したら押してください';
      check.addEventListener('click', ev => {
        ev.stopPropagation();
        e.confirmed = !e.confirmed;
        this.op(e.confirmed ? 'confirm' : 'unconfirm', {
          field: f.id, label: f.label,
          conf: e.confidence == null ? null : Math.round(e.confidence * 100),
        });
        const lv = this.levelOf(e);
        el.className = `field lv-${lv} active`;
        const bd = el.querySelector('.conf');
        bd.className = `conf ${lv}`;
        bd.innerHTML = (lv === 'anon' || lv === 'done')
          ? `<span class="dot"></span>${LEVEL_LABEL[lv]}`
          : `<span class="dot"></span>${LEVEL_LABEL[lv]} ${(e.confidence * 100).toFixed(0)}%`;
        check.classList.toggle('on', !!e.confirmed);
        check.textContent = e.confirmed ? '確定済み' : '確定';
        this.app.touch();
        this.updateStats();
      });
      // 何も書かれていない欄にOCRが文字を入れてしまうことがあるので、
      // 「消してから確定」を1操作でできるようにする。
      const clear = document.createElement('button');
      clear.type = 'button';
      clear.className = 'clearfix';
      clear.textContent = '削除して確定';
      clear.title = 'この欄を空にして確定します（記入が無い欄に文字が入った場合に使います）';
      clear.addEventListener('click', ev => {
        ev.stopPropagation();
        const L = global.IkenshoOpLog;
        this.op('clear_confirm', {
          field: f.id, label: f.label,
          before: L ? L.shape(e.date || e.value, f.pii) : '', after: '',
          blen: L ? L.len(e.date || e.value) : null, alen: 0,
        });
        e.value = (f.type === 'multi') ? [] : (f.type === 'flag' ? false : null);
        if (f.kind === 'date_wareki') e.date = { year: null, month: null, day: null };
        e.gregorian = null;
        e.raw = '';
        e.candidates = [];
        e.edited = true;
        e.confirmed = true;
        this.app.touch();
        this.renderFields();
        const again = this.fieldsEl.querySelector(`.field[data-field="${f.id}"]`);
        if (again) this.focusField(f.id, again);
      });
      head.appendChild(clear);
      head.appendChild(check);
      el.appendChild(head);

      el.appendChild(this.control(f, e, el));

      if (e.corrections && e.corrections.length) {
        const c = document.createElement('div');
        c.className = 'raw';
        c.textContent = '訂正: ' + e.corrections.slice(0, 4).map(x => {
          const before = x[0] !== undefined ? x[0] : x.before;
          const after = x[1] !== undefined ? x[1] : x.after;
          // 「先頭の記号を削除」のように、前後の文字ではなく理由だけを持つものもある
          if (!before && !after) return x.reason || '';
          return `${before}→${after || '（削除）'}`;
        }).filter(Boolean).join('、');
        el.appendChild(c);
      }
      if (e.note) {
        const n = document.createElement('div');
        n.className = 'raw';
        n.textContent = '※ ' + e.note;
        el.appendChild(n);
      }
      // チェック欄の後ろの言葉が定義と違って読めた／直されている場合に知らせる
      const notes = e.labelNotes || e.label_notes;
      if (Array.isArray(notes) && notes.length) {
        const changed = notes.filter(m => m.changed);
        const fixed = notes.filter(m => m.source === '修正');
        const parts = [];
        if (changed.length) {
          parts.push('様式の言葉が定義と違って読めました: '
            + changed.map(m => `${m.expected}→${m.read}`).join('、')
            + '（管理画面の「チェック欄の言葉」で直せます）');
        }
        if (fixed.length) {
          parts.push('管理画面で直した言葉を使っています: '
            + fixed.map(m => `${m.expected}→${m.word}`).join('、'));
        }
        const n = document.createElement('div');
        n.className = 'raw';
        n.textContent = '※ ' + parts.join(' / ');
        el.appendChild(n);
      }
      if (f.kind !== 'date_wareki' && e.raw && String(e.raw) !== String(e.value || '')) {
        const raw = document.createElement('div');
        raw.className = 'raw';
        raw.textContent = `OCR生読み: ${e.raw}`;
        el.appendChild(raw);
      }
      el.addEventListener('click', ev => {
        if (ev.target.closest('input,textarea,select,button,label')) return;
        this.focusField(f.id, el);
      });
      el.addEventListener('focusin', () => this.focusField(f.id, el));
      return el;
    }

    control(f, e, rowEl) {
      const wrap = document.createElement('div');
      const L = global.IkenshoOpLog;
      const src = e.date || e.value;
      const before = Array.isArray(src) ? src.slice()
        : (src && typeof src === 'object' ? Object.assign({}, src) : src);
      const mark = () => {
        if (L) L.edit(this.record, f, e, before);
        e.edited = true;
        e.level = 'edited';
        rowEl.className = 'field lv-edited active';
        const badge = rowEl.querySelector('.conf');
        badge.className = 'conf edited';
        badge.innerHTML = `<span class="dot"></span>修正`;
        this.app.touch();
      };

      // 実物のチェック欄の言葉（OCR で読んだ／管理画面で直した）を使う。
      // 出力の JSON もこの言葉になるので、画面と出力を揃える。
      const labelsOf = e.optionWords || f.options || [];

      if (f.type === 'choice' || f.type === 'circle') {
        const rows = (f.type === 'choice') ? this.optionRows(f) : null;
        const opts = document.createElement('div');
        opts.className = rows ? 'opts rows' : 'opts';
        const detail = e.detail || [];
        const makeBtn = (o, i) => {
          const d = detail.find(x => x.opt === i);
          const b = document.createElement('button');
          b.type = 'button';
          b.className = 'opt' + (e.value === o ? ' on' : '');
          b.innerHTML = `${esc(o)}${d && d.fill !== undefined ?
            `<span class="fill">${(d.fill * 100).toFixed(0)}</span>` : ''}`;
          b.addEventListener('click', () => {
            e.value = (e.value === o) ? null : o;
            opts.querySelectorAll('.opt').forEach(x => x.classList.remove('on'));
            if (e.value === o) b.classList.add('on');
            mark();
          });
          return b;
        };
        if (rows) {
          for (const row of rows) {
            const line = document.createElement('div');
            line.className = 'optrow';
            for (const i of row) line.appendChild(makeBtn(labelsOf[i], i));
            opts.appendChild(line);
          }
        } else {
          labelsOf.forEach((o, i) => opts.appendChild(makeBtn(o, i)));
        }
        wrap.appendChild(opts);
        return wrap;
      }

      if (f.type === 'multi') {
        const rows = this.optionRows(f);
        const opts = document.createElement('div');
        opts.className = rows ? 'opts rows' : 'opts';
        const detail = e.detail || [];
        const cur = new Set(Array.isArray(e.value) ? e.value : []);
        const makeBtn = (o, i) => {
          const d = detail.find(x => x.opt === i);
          const b = document.createElement('button');
          b.type = 'button';
          b.className = 'opt' + (cur.has(o) ? ' on' : '');
          b.innerHTML = `${esc(o)}${d && d.fill !== undefined ?
            `<span class="fill">${(d.fill * 100).toFixed(0)}</span>` : ''}`;
          b.addEventListener('click', () => {
            if (cur.has(o)) { cur.delete(o); b.classList.remove('on'); }
            else { cur.add(o); b.classList.add('on'); }
            e.value = labelsOf.filter(x => cur.has(x));
            mark();
          });
          return b;
        };
        if (rows) {
          for (const row of rows) {
            const line = document.createElement('div');
            line.className = 'optrow';
            for (const i of row) line.appendChild(makeBtn(labelsOf[i], i));
            opts.appendChild(line);
          }
        } else {
          labelsOf.forEach((o, i) => opts.appendChild(makeBtn(o, i)));
        }
        wrap.appendChild(opts);
        return wrap;
      }

      if (f.type === 'flag') {
        const b = document.createElement('button');
        b.type = 'button';
        b.className = 'opt' + (e.value ? ' on' : '');
        const d = (e.detail || [])[0];
        b.innerHTML = `該当あり${d ? `<span class="fill">${(d.fill * 100).toFixed(0)}</span>` : ''}`;
        b.addEventListener('click', () => {
          e.value = !e.value;
          b.classList.toggle('on', !!e.value);
          mark();
        });
        wrap.appendChild(b);
        return wrap;
      }

      if (f.kind === 'date_wareki') {
        return this.dateControl(f, e, wrap, mark);
      }

      // text / textarea
      const isArea = f.type === 'textarea';
      const input = document.createElement(isArea ? 'textarea' : 'input');
      if (!isArea) input.type = 'text';
      input.value = e.value == null ? '' : String(e.value);
      if (f.hint) input.placeholder = f.hint;
      input.addEventListener('input', () => {
        e.value = input.value;
        mark();
        this.renderCandidates(f, e, wrap, input);
      });
      if (f.charset === 'kana') {
        // 様式は「ふりがな」なので、カタカナで入っていたらひらがなに直す
        input.addEventListener('blur', () => {
          const fixed = toHiragana(input.value);
          if (fixed !== input.value) {
            input.value = fixed;
            input.dispatchEvent(new Event('input'));
            this.op('kana_fix', { field: f.id, label: f.label });
            this.app.toast('ふりがなをひらがなに直しました');
          }
        });
      }
      wrap.appendChild(input);
      // 医療機関名は一覧から選べるようにする。選ぶと所在地と電話も埋まる。
      if (f.id === 'clinic_name') this.renderHospitalPicker(f, e, wrap, input, mark);
      // 記述欄は打ち込みが大変なので、音声でも入れられるようにする
      if (isArea) this.renderDictation(f, e, wrap, input, mark);
      this.renderCandidates(f, e, wrap, input);
      if (!isArea) this.renderSearch(f, e, wrap, input);
      return wrap;
    }

    /**
     * 和暦の日付欄。年・月・日を別々の数字入力にして、
     * 数字を埋めるだけで直せるようにする。西暦も合わせて表示する。
     */
    dateControl(f, e, wrap, mark) {
      const D = global.IkenshoDates;
      const parts = Object.assign({ year: null, month: null, day: null }, e.date || {});
      let era = e.era || f.default_era || '';

      const row = document.createElement('div');
      row.className = 'daterow';

      // 元号: 別の項目から取っている場合は表示のみ、そうでなければ選べる
      const eraFrom = f.era_field ? this.record.fields[f.era_field] : null;
      if (f.default_era) {
        const fixed = document.createElement('span');
        fixed.className = 'era fixed';
        fixed.textContent = f.default_era;
        row.appendChild(fixed);
        era = f.default_era;
      } else {
        const sel = document.createElement('select');
        sel.className = 'era';
        sel.innerHTML = '<option value="">元号</option>' +
          D.ERA_LIST.map(x => `<option value="${x}">${x}</option>`).join('');
        sel.value = D.canonicalEra(era) || '';
        sel.addEventListener('change', () => {
          era = sel.value;
          if (eraFrom && f.era_field) {
            eraFrom.value = sel.value ? sel.value.slice(0, f.era_field === 'birth_era' ? 1 : 2) : null;
            eraFrom.edited = true;
            eraFrom.level = 'edited';
          }
          apply();
        });
        row.appendChild(sel);
      }

      const inputs = {};
      for (const [key, label, max] of [['year', '年', 4], ['month', '月', 2], ['day', '日', 2]]) {
        const box = document.createElement('span');
        box.className = 'datebox';
        const inp = document.createElement('input');
        inp.type = 'text';
        inp.inputMode = 'numeric';
        inp.autocomplete = 'off';
        inp.maxLength = max;
        inp.placeholder = '—';
        inp.value = (parts[key] === null || parts[key] === undefined) ? '' : String(parts[key]);
        inp.addEventListener('input', () => {
          inp.value = inp.value.replace(/[^0-9]/g, '').slice(0, max);
          // 埋まったら次の欄へ自動で移る
          if (inp.value.length >= (key === 'year' ? 2 : 2)) {
            const order = ['year', 'month', 'day'];
            const next = order[order.indexOf(key) + 1];
            if (next && inputs[next] && !inputs[next].value) inputs[next].focus();
          }
          apply();
        });
        inputs[key] = inp;
        box.appendChild(inp);
        const unit = document.createElement('span');
        unit.className = 'unit';
        unit.textContent = label;
        box.appendChild(unit);
        row.appendChild(box);
      }

      const info = document.createElement('span');
      info.className = 'seireki';
      row.appendChild(info);
      wrap.appendChild(row);

      const raw = document.createElement('div');
      raw.className = 'raw';
      wrap.appendChild(raw);

      const self = this;
      function apply(initial) {
        const p = {};
        for (const k of ['year', 'month', 'day']) {
          const v = inputs[k].value.trim();
          p[k] = v === '' ? null : parseInt(v, 10);
        }
        e.date = p;
        e.era = D.canonicalEra(era);
        e.value = D.format(p);
        e.gregorian = D.toGregorian(e.era, p.year, p.month, p.day);
        info.textContent = e.gregorian ? `西暦 ${e.gregorian}` : '';
        info.classList.toggle('none', !e.gregorian);
        raw.textContent = e.raw ? `OCR生読み: ${e.raw}` : '';
        if (!initial) mark();
      }
      apply(true);
      return wrap;
    }

    /**
     * 医療機関名を一覧から選ぶ。厚生労働省の保険医療機関一覧を使う。
     * 選ぶと所在地と電話番号も一緒に埋まるので、打ち直さずに済む。
     */
    async renderHospitalPicker(f, e, wrap, input, mark) {
      const base = this.app.pipeline.base;
      if (!this._hospIndex) {
        try {
          this._hospIndex = await fetch(`${base}/dict/hospitals/index.json`).then(r => r.json());
        } catch (err) { this._hospIndex = { prefectures: [] }; }
      }
      const idx = this._hospIndex;
      if (!idx.prefectures || !idx.prefectures.length) return;

      const box = document.createElement('div');
      box.className = 'hosppick';
      const pref = document.createElement('select');
      pref.innerHTML = '<option value="">都道府県</option>' +
        idx.prefectures.map(p => `<option value="${esc(p.pref)}">${esc(p.pref)}（${p.count}）</option>`).join('');
      const q = document.createElement('input');
      q.type = 'search';
      q.placeholder = '医療機関名で探す';
      q.disabled = true;
      const list = document.createElement('div');
      list.className = 'dictlist';
      list.hidden = true;
      box.appendChild(pref); box.appendChild(q); box.appendChild(list);
      wrap.appendChild(box);

      // 住所から都道府県が分かれば最初から選んでおく
      const addr = (this.record.fields.clinic_address || {}).value || '';
      const guess = idx.prefectures.find(p => String(addr).startsWith(p.pref));
      let entries = null;

      const load = async name => {
        if (!name) { entries = null; q.disabled = true; return; }
        q.disabled = true;
        q.placeholder = `${name} を読み込んでいます…`;
        try {
          const d = await fetch(`${base}/dict/hospitals/${encodeURIComponent(name)}.json`)
            .then(r => r.json());
          entries = d.entries || [];
          q.placeholder = `${name}の医療機関から探す（${entries.length}件）`;
          q.disabled = false;
        } catch (err) {
          entries = null;
          q.placeholder = '一覧を読み込めませんでした';
        }
      };
      const draw = () => {
        if (!entries) { list.hidden = true; return; }
        const N = global.IkenshoDicts.normalize;
        const key = N(q.value || input.value || '');
        let hits = key
          ? entries.filter(h => N(h.name).includes(key)).slice(0, 40)
          : entries.slice(0, 40);
        if (key && hits.length < 8) {
          const more = entries
            .map(h => ({ h, s: global.IkenshoDicts.similarity(key, h.name) }))
            .filter(x => x.s >= 0.5).sort((a, b) => b.s - a.s).slice(0, 20).map(x => x.h);
          for (const h of more) if (!hits.includes(h)) hits.push(h);
        }
        list.hidden = false;
        if (!hits.length) { list.innerHTML = '<div class="none">該当なし</div>'; return; }
        list.replaceChildren();
        for (const h of hits) {
          const b = document.createElement('button');
          b.type = 'button';
          b.className = 'dictitem';
          b.innerHTML = `${esc(h.name)}<span class="icd">${esc(h.address || '')}</span>`;
          b.addEventListener('click', () => {
            input.value = h.name;
            input.dispatchEvent(new Event('input'));
            this.applyHospital(h);
            list.hidden = true;
          });
          list.appendChild(b);
        }
      };
      pref.addEventListener('change', async () => { await load(pref.value); draw(); });
      q.addEventListener('focus', draw);
      q.addEventListener('input', draw);
      q.addEventListener('blur', () => setTimeout(() => { list.hidden = true; }, 200));
      if (guess) { pref.value = guess.pref; await load(guess.pref); }
    }

    /** 選んだ医療機関の所在地・電話を、対応する欄に入れる。 */
    applyHospital(h) {
      const L = global.IkenshoOpLog;
      const byId = this.app.schema.byId;
      const set = (id, value) => {
        const e = this.record.fields[id];
        if (!e || !value) return;
        // 自動で入れた欄も、何が入ったか分かるように記録する
        this.op('hospital', {
          field: id, label: (byId[id] || {}).label || id,
          before: L ? L.shape(e.value, (byId[id] || {}).pii) : '',
          after: L ? L.shape(value, (byId[id] || {}).pii) : '',
          blen: L ? L.len(e.value) : null, alen: L ? L.len(value) : null,
          note: '一覧から選んだ医療機関に合わせて入力',
        });
        e.value = value;
        e.edited = true;
        e.level = 'edited';
      };
      this.op('hospital', {
        field: 'clinic_name', label: '医療機関名',
        after: L ? L.shape(h.name, (byId.clinic_name || {}).pii) : '',
        alen: L ? L.len(h.name) : null,
        note: '一覧から選択',
      });
      set('clinic_address', h.address);
      set('clinic_phone', h.phone);
      this.app.toast(`${h.name} の所在地と電話番号を入れました`);
      this.app.touch();
      this.renderFields();
      const el = this.fieldsEl.querySelector('.field[data-field="clinic_name"]');
      if (el) this.focusField('clinic_name', el);
    }

    /**
     * 記述欄の音声入力。話した内容がそのまま欄に入る。
     * ブラウザの音声認識を使うため、初回に注意を出す（speech.js を参照）。
     */
    renderDictation(f, e, wrap, input, mark) {
      const S = global.IkenshoSpeech;
      if (!S || !S.supported()) return;
      const bar = document.createElement('div');
      bar.className = 'dictate';
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'micbtn';
      btn.innerHTML = '<span class="mic">●</span> 音声で入力';
      const state = document.createElement('span');
      state.className = 'dictstate';
      bar.appendChild(btn);
      bar.appendChild(state);
      wrap.appendChild(bar);

      const dictation = new S.Dictation({
        onText: (text, interim) => {
          input.value = text;
          e.value = text;
          if (!interim) mark();
        },
        onState: (kind, message) => {
          btn.classList.toggle('on', kind === 'listening');
          btn.innerHTML = kind === 'listening'
            ? '<span class="mic on"></span> 停止する'
            : '<span class="mic"></span> 音声で入力';
          state.textContent = kind === 'listening' ? '話してください…' : (message || '');
          state.className = 'dictstate' + (kind === 'error' ? ' err' : '');
          if (kind === 'stopped') {
            mark();
            this.op('dictation', { field: f.id, label: f.label });
          }
        },
      });
      btn.addEventListener('click', ev => {
        ev.stopPropagation();
        if (dictation.active) dictation.stop();
        else dictation.start(input.value);
      });
      this._dictations = this._dictations || [];
      this._dictations.push(dictation);
    }

    /**
     * 辞書から探すための欄。病名などは一覧から選べた方が速く確実なので、
     * 入力欄とは別に「探す」欄を用意して、打ち込みながら絞り込めるようにする。
     */
    renderSearch(f, e, wrap, input) {
      const dicts = this.app.pipeline && this.app.pipeline.dicts;
      const key = dicts && dicts.fieldMap[f.id];
      if (!key) return;
      const lex = dicts.lexicons[key];
      if (!lex) return;

      const box = document.createElement('div');
      box.className = 'dictsearch';
      const q = document.createElement('input');
      q.type = 'search';
      q.placeholder = `${lex.label}から探す（${lex.entries.length}件）`;
      const list = document.createElement('div');
      list.className = 'dictlist';
      list.hidden = true;

      const draw = () => {
        const items = dicts.suggest(f.id, q.value, 30);
        if (!items.length) {
          list.innerHTML = '<div class="none">該当なし</div>';
          return;
        }
        list.replaceChildren();
        for (const it of items) {
          const b = document.createElement('button');
          b.type = 'button';
          b.className = 'dictitem';
          b.innerHTML = esc(it.name) +
            (it.tokutei ? '<span class="tok">特定疾病</span>' : '') +
            (it.icd10 ? `<span class="icd">${esc(it.icd10)}</span>` : '');
          b.addEventListener('click', () => {
            input.value = it.name;
            input.dispatchEvent(new Event('input'));
            q.value = '';
            list.hidden = true;
          });
          list.appendChild(b);
        }
      };
      q.addEventListener('focus', () => { list.hidden = false; draw(); });
      q.addEventListener('input', () => { list.hidden = false; draw(); });
      q.addEventListener('blur', () => setTimeout(() => { list.hidden = true; }, 200));
      box.appendChild(q);
      box.appendChild(list);
      wrap.appendChild(box);
    }

    /** 辞書からの候補（OCR補正候補＋入力補完）を出す。 */
    renderCandidates(f, e, wrap, input) {
      let box = wrap.querySelector('.cands');
      if (box) box.remove();
      const dicts = this.app.pipeline && this.app.pipeline.dicts;
      if (!dicts || !dicts.fieldMap[f.id]) return;

      let items = [];
      const q = input.value.trim();
      // OCRの生読みも意外に当たっているので候補に入れる
      const rawItem = (e.raw && String(e.raw).trim() && String(e.raw).trim() !== q)
        ? { value: String(e.raw).trim(), source: 'raw' } : null;
      if (q) {
        items = dicts.suggest(f.id, q, 8).map(x => ({
          value: x.name, icd10: x.icd10 || '', tokutei: !!x.tokutei
        }));
      } else if (e.candidates && e.candidates.length) {
        items = e.candidates.slice(0, 8).map(c => ({
          value: c.value, icd10: c.icd10 || '', tokutei: !!c.tokutei, source: c.source || ''
        }));
      } else {
        items = dicts.suggest(f.id, '', 8).map(x => ({
          value: x.name, icd10: x.icd10 || '', tokutei: !!x.tokutei
        }));
      }
      if (rawItem && !items.some(x => x.value === rawItem.value)) items.unshift(rawItem);
      items = items.filter(x => x.value !== q);
      if (!items.length) return;

      box = document.createElement('div');
      box.className = 'cands';
      for (const it of items) {
        const b = document.createElement('button');
        b.type = 'button';
        b.className = 'cand';
        b.innerHTML = esc(it.value) +
          (it.source === 'llm' ? '<span class="llm">LLM候補</span>' : '') +
          (it.source === 'raw' ? '<span class="rawtag">OCR生読み</span>' : '') +
          (it.tokutei ? '<span class="tok">特定疾病</span>' : '') +
          (it.icd10 ? `<span class="icd">${esc(it.icd10)}</span>` : '');
        if (it.source === 'raw') {
          b.classList.add('rawcand');
          b.title = 'OCRがそのまま読み取った文字列です。辞書に無い語のときに使えます。';
        }
        if (it.source === 'llm') {
          b.classList.add('llmcand');
          b.title = 'LLMが提示した候補です。内容を確認してから採用してください。';
        }
        b.addEventListener('click', () => {
          const L = global.IkenshoOpLog;
          this.op('candidate', {
            field: f.id, label: f.label,
            before: L ? L.shape(e.value, f.pii) : '',
            after: L ? L.shape(it.value, f.pii) : '',
            blen: L ? L.len(e.value) : null, alen: L ? L.len(it.value) : null,
            note: { llm: 'LLM候補', raw: 'OCR生読み' }[it.source] || '辞書候補',
          });
          input.value = it.value;
          input.dispatchEvent(new Event('input'));
          input.focus();
        });
        box.appendChild(b);
      }
      wrap.appendChild(box);
    }

    // ------------------------------------------------- 元画像との突き合わせ
    focusField(fieldId, el) {
      this.fieldsEl.querySelectorAll('.field.active').forEach(x => x.classList.remove('active'));
      const host = document.getElementById('hotspots');
      if (host) {
        host.querySelectorAll('.hot.sel').forEach(x => x.classList.remove('sel'));
      }
      if (el) el.classList.add('active');
      this.activeField = fieldId;
      const loc = this.locate(fieldId);
      if (!loc) { this.marker.hidden = true; this.zoom.replaceChildren(); return; }
      if (loc.page !== this.currentPage) this.showPage(loc.page);
      const [x, y, w, h] = loc.rect;
      this.marker.hidden = false;
      const sc = document.getElementById('scroller');
      if (sc && this.imgEl.naturalHeight) {
        const target = (y + h / 2) * this.imgEl.clientHeight - sc.clientHeight / 2;
        sc.scrollTo({ top: Math.max(0, target), behavior: 'smooth' });
      }
      this.marker.style.left = (x * 100) + '%';
      this.marker.style.top = (y * 100) + '%';
      this.marker.style.width = (w * 100) + '%';
      this.marker.style.height = (h * 100) + '%';
      this.renderZoom(loc);
      this.updateVlmButton(fieldId);
      if (host) {
        host.querySelectorAll('.hot').forEach(h => {
          if (h.dataset.field === fieldId) h.classList.add('sel');
        });
      }
    }

    /**
     * 「この欄をVLMで読み直す」ボタンの出し入れ。
     * VLM は1欄で数秒かかるので、全欄を通すのではなく
     * **読めていない欄だけを指して読み直す**のが現実的な使い方。
     */
    updateVlmButton(fieldId) {
      const btn = document.getElementById('btn-vlm-field');
      const box = document.getElementById('vlm-field-status');
      if (btn) {
        const f = this.app.schema.byId[fieldId];
        const ok = !!(this.app.pipeline.vlmEndpoint) && f && f.type !== 'choice'
                   && f.type !== 'multi' && f.type !== 'flag' && f.type !== 'circle'
                   && !!(this.record.images || {})[this.currentPage];
        btn.hidden = !ok;
        btn.disabled = false;
        btn.textContent = 'この欄をVLMで読み直す';
      }
      if (box) box.hidden = true;
    }

    /** いま選んでいる欄だけを VLM で読み直す。 */
    async rereadWithVlm() {
      const fieldId = this.activeField;
      const f = this.app.schema.byId[fieldId];
      const loc = this.locate(fieldId);
      const src = (this.record.images || {})[loc && loc.page];
      const btn = document.getElementById('btn-vlm-field');
      const box = document.getElementById('vlm-field-status');
      if (!f || !loc || !src) return;
      const say = (msg, err) => {
        if (!box) return;
        box.hidden = false;
        box.textContent = msg;
        box.style.color = err ? 'var(--low)' : '';
      };
      btn.disabled = true;
      btn.textContent = '読み直しています…';
      say('VLMに渡しています（数秒かかります）');
      try {
        const url = await this.cropDataUrl(src, loc.rect);
        const res = await fetch(this.app.pipeline.vlmEndpoint, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ image: url, charset: f.charset || '',
                                 multiline: f.type === 'textarea' }),
        });
        const got = await res.json();
        if (!res.ok || got.error) { say(got.error || `HTTP ${res.status}`, true); return; }
        const text = (got.text || '').trim();
        if (!text) { say('VLMでも文字を読み取れませんでした', true); return; }
        const e = this.record.fields[fieldId];
        const before = e.value;
        e.value = text;
        e.raw = text;
        e.engine = got.engine || 'vlm';
        // 日付欄は年・月・日と西暦も作り直す。値だけ差し替えると食い違う
        if (f.kind === 'date_wareki') {
          const D = global.IkenshoDates;
          const parts = D.parse(text);
          const era = D.canonicalEra(f.default_era || parts.era || e.era || '');
          e.date = { year: parts.year, month: parts.month, day: parts.day };
          e.era = era;
          e.gregorian = D.toGregorian(era, parts.year, parts.month, parts.day);
          const shown = D.format(e.date);
          if (shown) e.value = shown;
        }
        e.note = 'VLMで読み直しました（内容を確かめてください）';
        // VLM は自己申告しないので確信度は上げない。必ず確認してもらう
        e.confidence = Math.min(e.confidence || 0, got.confidence || 0.5);
        e.level = 'low';
        const L = global.IkenshoOpLog;
        if (L) L.edit(this.record, f, e, before);
        this.app.touch();
        this.renderFields();
        this.focusField(fieldId, null);
        say(`VLMの読み: ${text}`);
      } catch (err) {
        say('読み直しに失敗しました: ' + err.message, true);
      } finally {
        btn.disabled = false;
        btn.textContent = 'この欄をVLMで読み直す';
      }
    }

    /** ページ画像から欄の部分だけを切り出し、PNG の data URL にする。 */
    cropDataUrl(src, rect, pad = 0.004) {
      return new Promise((res, rej) => {
        const img = new Image();
        img.onerror = () => rej(new Error('画像を読めません'));
        img.onload = () => {
          const x = Math.max(0, (rect[0] - pad) * img.width);
          const y = Math.max(0, (rect[1] - pad) * img.height);
          const w = Math.min(img.width - x, (rect[2] + pad * 2) * img.width);
          const h = Math.min(img.height - y, (rect[3] + pad * 2) * img.height);
          const c = document.createElement('canvas');
          c.width = Math.max(1, Math.round(w)); c.height = Math.max(1, Math.round(h));
          const ctx = c.getContext('2d');
          ctx.drawImage(img, x, y, w, h, 0, 0, c.width, c.height);
          res(c.toDataURL('image/png'));
        };
        img.src = src;
      });
    }

    /** テンプレートから、その項目が画像上のどこにあるかを求める。 */
    locate(fieldId) {
      const tpl = this.app.pipeline.templates[this.record.templateId];
      if (!tpl) return null;
      for (const p of tpl.pages) {
        const t = p.texts.find(t => t.field === fieldId);
        if (t) return { page: p.index, rect: t.rect };
        const bs = p.boxes.filter(b => b.field === fieldId);
        if (bs.length) {
          const x0 = Math.min(...bs.map(b => b.rect[0]));
          const y0 = Math.min(...bs.map(b => b.rect[1]));
          const x1 = Math.max(...bs.map(b => b.rect[0] + b.rect[2]));
          const y1 = Math.max(...bs.map(b => b.rect[1] + b.rect[3]));
          // ラベル側も見えるよう少し広げる
          const padX = Math.min(0.30, (x1 - x0) * 0.6 + 0.10);
          return { page: p.index,
                   rect: [Math.max(0, x0 - 0.01), Math.max(0, y0 - 0.006),
                          Math.min(1, x1 - x0 + padX), Math.min(1, y1 - y0 + 0.012)] };
        }
      }
      return null;
    }

    renderZoom(loc) {
      this._lastLoc = loc;
      const src = (this.record.images || {})[loc.page];
      if (!src) { this.zoom.replaceChildren(); return; }
      const img = new Image();
      img.onload = () => {
        const pad = 0.012;
        const x = Math.max(0, (loc.rect[0] - pad) * img.width);
        const y = Math.max(0, (loc.rect[1] - pad) * img.height);
        const w = Math.min(img.width - x, (loc.rect[2] + pad * 2) * img.width);
        const h = Math.min(img.height - y, (loc.rect[3] + pad * 2) * img.height);
        // 幅に合わせて縮めると長い欄が読めなくなるので、高さを基準に拡大し、
        // 横は切らずにスクロールで追えるようにする。
        const base = Math.min(5, Math.max(1.6, 150 / Math.max(h, 1)));
        const scale = base * (this.zoomScale || 1);
        const c = document.createElement('canvas');
        c.width = Math.round(w * scale); c.height = Math.round(h * scale);
        const ctx = c.getContext('2d');
        ctx.imageSmoothingQuality = 'high';
        ctx.drawImage(img, x, y, w, h, 0, 0, c.width, c.height);
        this.zoom.replaceChildren(c);
        this.zoom.scrollLeft = 0;
        this.bindZoomPan();
        // 横に続いていることが分かるよう、はみ出す場合だけ案内を出す
        const over = this.zoom.scrollWidth > this.zoom.clientWidth + 4;
        if (this.zoomHint) this.zoomHint.hidden = !over;
      };
      img.src = src;
      this.zoomcap.textContent = `${loc.page}ページ目の該当箇所`;
    }

    /**
     * 拡大表示を横に動かせるようにする。
     * スクロールバーだけでは気づきにくいので、掴んで動かす操作と、
     * ホイールでの横移動も付ける。
     */
    bindZoomPan() {
      if (this._zoomPanBound) return;
      this._zoomPanBound = true;
      const z = this.zoom;
      // ホイールは縦にしか効かないので、横に流せる場合は横に回す
      z.addEventListener('wheel', ev => {
        const over = z.scrollWidth > z.clientWidth + 4;
        if (!over) return;
        const dx = Math.abs(ev.deltaX) > Math.abs(ev.deltaY) ? ev.deltaX : ev.deltaY;
        if (!dx) return;
        const before = z.scrollLeft;
        z.scrollLeft += dx;
        if (z.scrollLeft !== before) ev.preventDefault();
      }, { passive: false });

      let drag = null;
      z.addEventListener('pointerdown', ev => {
        if (ev.button !== 0) return;
        drag = { x: ev.clientX, y: ev.clientY,
                 left: z.scrollLeft, top: z.scrollTop, id: ev.pointerId };
        z.classList.add('grabbing');
        z.setPointerCapture(ev.pointerId);
      });
      const end = ev => {
        if (!drag) return;
        z.classList.remove('grabbing');
        try { z.releasePointerCapture(drag.id); } catch (e) { /* すでに解放済み */ }
        drag = null;
      };
      z.addEventListener('pointermove', ev => {
        if (!drag) return;
        z.scrollLeft = drag.left - (ev.clientX - drag.x);
        z.scrollTop = drag.top - (ev.clientY - drag.y);
      });
      z.addEventListener('pointerup', end);
      z.addEventListener('pointercancel', end);
      z.addEventListener('pointerleave', end);
    }

    jumpLow(dir) {
      const ids = this.app.schema.order.filter(id => {
        const e = this.record && this.record.fields[id];
        return e && this.needsCheck(e);
      });
      if (!ids.length) return;
      let i = ids.indexOf(this.activeField);
      i = (i < 0) ? (dir > 0 ? 0 : ids.length - 1) : (i + dir + ids.length) % ids.length;
      const id = ids[i];
      const el = this.fieldsEl.querySelector(`.field[data-field="${id}"]`);
      if (el) { el.scrollIntoView({ block: 'center', behavior: 'smooth' }); this.focusField(id, el); }
      else this.focusField(id, null);
    }
  }

  /** カタカナをひらがなに直す。長音符や記号はそのまま。 */
  function toHiragana(text) {
    let out = '';
    for (const ch of String(text || '')) {
      const c = ch.codePointAt(0);
      out += (c >= 0x30A1 && c <= 0x30F6) ? String.fromCodePoint(c - 0x60) : ch;
    }
    return out;
  }

  function isEmptyValue(v) {
    return v === null || v === undefined || v === '' || v === false ||
           (Array.isArray(v) && v.length === 0);
  }

  function esc(s) {
    return String(s).replace(/[&<>"']/g, c =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  global.IkenshoReview = Review;
  global.IkenshoUtil = { esc, isEmptyValue };
})(window);
