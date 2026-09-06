/**
 * 確認・編集画面。
 * 読み取り値・確信度・元画像の切り抜きを並べ、その場で修正できるようにする。
 */
(function (global) {
  'use strict';

  const LEVEL_LABEL = { high: '高', medium: '中', low: '低', edited: '修正', anon: '匿名化' };

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
        el.className = 'hot';
        el.style.left = (s.rect[0] * 100) + '%';
        el.style.top = (s.rect[1] * 100) + '%';
        el.style.width = (s.rect[2] * 100) + '%';
        el.style.height = (s.rect[3] * 100) + '%';
        const f = this.app.schema.byId[s.field];
        el.title = f ? f.label : s.field;
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
      const s = { high: 0, medium: 0, low: 0, edited: 0, filled: 0, total: 0 };
      for (const id of this.app.schema.order) {
        const e = this.record.fields[id];
        if (!e) continue;
        s.total++;
        if (e.edited) s.edited++;
        else s[e.level]++;
        if (!isEmptyValue(e.value)) s.filled++;
      }
      return s;
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
      const schema = this.app.schema;
      const frag = document.createDocumentFragment();

      const st = this.stats();
      const head = document.createElement('div');
      head.className = 'panel';
      head.style.padding = '10px 14px';
      head.innerHTML = `<div class="row" style="font-size:12.5px">
        <span>読み取り ${st.filled} / ${st.total} 項目</span>
        <span class="conf high"><span class="dot"></span>高 ${st.high}</span>
        <span class="conf medium"><span class="dot"></span>中 ${st.medium}</span>
        <span class="conf low"><span class="dot"></span>低 ${st.low}</span>
        <span class="conf edited"><span class="dot"></span>修正 ${st.edited}</span></div>`;
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
    }

    needsCheck(e) {
      if (e.anonymized) return false;
      return !e.edited && (e.level === 'low' || e.level === 'medium');
    }

    // ------------------------------------------------------- 1項目の描画
    fieldRow(f, e) {
      const el = document.createElement('div');
      const level = e.anonymized ? 'anon' : (e.edited ? 'edited' : e.level);
      el.className = `field lv-${level}`;
      el.dataset.field = f.id;

      const head = document.createElement('div');
      head.className = 'head';
      head.innerHTML = e.anonymized
        ? `<span class="lbl">${esc(f.label)}</span>
           <span class="conf anon"><span class="dot"></span>匿名化</span>`
        : `<span class="lbl">${esc(f.label)}</span>
           <span class="conf ${level}"><span class="dot"></span>${LEVEL_LABEL[level]} ${
             (e.confidence * 100).toFixed(0)}%</span>`;
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
      if (e.raw && String(e.raw) !== String(e.value || '')) {
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
        const opts = document.createElement('div');
        opts.className = 'opts';
        const detail = e.detail || [];
        (f.options || []).forEach((o, i) => {
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
          opts.appendChild(b);
        });
        wrap.appendChild(opts);
        return wrap;
      }

      if (f.type === 'multi') {
        const opts = document.createElement('div');
        opts.className = 'opts';
        const detail = e.detail || [];
        const cur = new Set(Array.isArray(e.value) ? e.value : []);
        (f.options || []).forEach((o, i) => {
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
          opts.appendChild(b);
        });
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
      wrap.appendChild(input);
      this.renderCandidates(f, e, wrap, input);
      return wrap;
    }

    /** 辞書からの候補（OCR補正候補＋入力補完）を出す。 */
    renderCandidates(f, e, wrap, input) {
      let box = wrap.querySelector('.cands');
      if (box) box.remove();
      const dicts = this.app.pipeline && this.app.pipeline.dicts;
      if (!dicts || !dicts.fieldMap[f.id]) return;

      let items = [];
      const q = input.value.trim();
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
          (it.tokutei ? '<span class="tok">特定疾病</span>' : '') +
          (it.icd10 ? `<span class="icd">${esc(it.icd10)}</span>` : '');
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
      const src = (this.record.images || {})[loc.page];
      if (!src) { this.zoom.replaceChildren(); return; }
      const img = new Image();
      img.onload = () => {
        const pad = 0.012;
        const x = Math.max(0, (loc.rect[0] - pad) * img.width);
        const y = Math.max(0, (loc.rect[1] - pad) * img.height);
        const w = Math.min(img.width - x, (loc.rect[2] + pad * 2) * img.width);
        const h = Math.min(img.height - y, (loc.rect[3] + pad * 2) * img.height);
        const scale = Math.min(4, Math.max(1.4, 620 / Math.max(w, 1)));
        const c = document.createElement('canvas');
        c.width = Math.round(w * scale); c.height = Math.round(h * scale);
        const ctx = c.getContext('2d');
        ctx.imageSmoothingQuality = 'high';
        ctx.drawImage(img, x, y, w, h, 0, 0, c.width, c.height);
        this.zoom.replaceChildren(c);
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
