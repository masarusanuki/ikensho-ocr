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
      this.onlyLow = false;
      this.imgEl = document.getElementById('page-img');
      this.marker = document.getElementById('marker');
      this.zoom = document.getElementById('zoom');
      this.zoomcap = document.getElementById('zoomcap');
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
        this.onlyLow = e.target.checked;
        this.renderFields();
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
      document.getElementById('opt-overlay').addEventListener('change', e => {
        document.getElementById('frame').classList.toggle('plain', !e.target.checked);
      });
      document.getElementById('btn-anon').addEventListener('click', () => this.toggleAnonymize());
      document.getElementById('btn-next-low').addEventListener('click', () => this.jumpLow(1));
      document.getElementById('btn-prev-low').addEventListener('click', () => this.jumpLow(-1));
    }

    // ------------------------------------------------------------ 表示
    show(record) {
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
      if (!el && this.onlyLow) {
        this.onlyLow = false;
        document.getElementById('only-low').checked = false;
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
      document.getElementById('page-title').textContent =
        src ? `元画像（${n}ページ目）` : `${n}ページ目は取り込まれていません`;
      this.imgEl.src = src || '';
      this.imgEl.style.visibility = src ? 'visible' : 'hidden';
      this.marker.hidden = true;
      this.renderHotspots();
    }

    renderWarnings() {
      const w = this.record.warnings || [];
      if (!w.length) { this.warnEl.innerHTML = ''; return; }
      this.warnEl.innerHTML =
        `<div class="warnbox"><strong>確認してください</strong><ul>${
          w.map(x => `<li>${esc(x)}</li>`).join('')}</ul></div>`;
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
      const s = { high: 0, medium: 0, low: 0, edited: 0, done: 0, filled: 0, total: 0 };
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

    /** 上部の集計を貼り替える。 */
    updateStats() {
      const st = this.stats();
      const host = this.fieldsEl.querySelector('.statrow');
      if (!host) return;
      host.innerHTML = `<span>読み取り ${st.filled} / ${st.total} 項目</span>
        <span class="conf done"><span class="dot"></span>確定 ${st.done}</span>
        <span class="conf high"><span class="dot"></span>高 ${st.high}</span>
        <span class="conf medium"><span class="dot"></span>中 ${st.medium}</span>
        <span class="conf low"><span class="dot"></span>低 ${st.low}</span>
        <span class="conf edited"><span class="dot"></span>修正 ${st.edited}</span>
        <button class="btn sm" id="btn-confirm-all">表示中をすべて確定</button>`;
      const all = host.querySelector('#btn-confirm-all');
      if (all) all.addEventListener('click', () => this.confirmAllVisible());
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
      const head = document.createElement('div');
      head.className = 'panel';
      head.style.padding = '10px 14px';
      head.innerHTML = '<div class="row statrow" style="font-size:12.5px"></div>';
      frag.appendChild(head);

      for (const sec of schema.sections) {
        const rows = [];
        for (const f of this.orderedFields(sec.fields)) {
          const e = this.record.fields[f.id];
          if (!e) continue;
          if (this.onlyLow && !this.needsCheck(e)) continue;
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
      }
      this.fieldsEl.replaceChildren(frag);
      this.updateStats();
      this.renderHotspots();
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

    fieldRow(f, e) {
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
      head.innerHTML = `<span class="lbl">${esc(f.label)}</span>${badge}`;

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
        c.textContent = '訂正: ' + e.corrections.slice(0, 4)
          .map(x => `${x[0] || x.before}→${(x[1] !== undefined ? x[1] : x.after) || '（削除）'}`)
          .join('、');
        el.appendChild(c);
      }
      if (e.note) {
        const n = document.createElement('div');
        n.className = 'raw';
        n.textContent = '※ ' + e.note;
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
      const mark = () => {
        e.edited = true;
        e.level = 'edited';
        rowEl.className = 'field lv-edited active';
        const badge = rowEl.querySelector('.conf');
        badge.className = 'conf edited';
        badge.innerHTML = `<span class="dot"></span>修正`;
        this.app.touch();
      };

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
            for (const i of row) line.appendChild(makeBtn(f.options[i], i));
            opts.appendChild(line);
          }
        } else {
          (f.options || []).forEach((o, i) => opts.appendChild(makeBtn(o, i)));
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
            e.value = (f.options || []).filter(x => cur.has(x));
            mark();
          });
          return b;
        };
        if (rows) {
          for (const row of rows) {
            const line = document.createElement('div');
            line.className = 'optrow';
            for (const i of row) line.appendChild(makeBtn(f.options[i], i));
            opts.appendChild(line);
          }
        } else {
          (f.options || []).forEach((o, i) => opts.appendChild(makeBtn(o, i)));
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
            this.app.toast('ふりがなをひらがなに直しました');
          }
        });
      }
      wrap.appendChild(input);
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
          if (kind === 'stopped') mark();
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
      if (host) {
        host.querySelectorAll('.hot').forEach(h => {
          if (h.dataset.field === fieldId) h.classList.add('sel');
        });
      }
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
      };
      img.src = src;
      this.zoomcap.textContent = `${loc.page}ページ目の該当箇所`;
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
