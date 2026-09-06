/**
 * 操作ログ。
 *
 * 「読み取った結果を、人がどこまで直したか」を後から確認できるようにする。
 * 読み取り精度の検証にも、確認作業の記録としても使う。
 *
 * 置き場所はブラウザ内（localStorage）だけで、どこにも送らない。
 * 氏名・住所など個人情報の項目（テンプレートで pii 指定のもの）は、
 * 値そのものを残さず「○文字」とだけ記録する。
 * 値を一切残したくない場合は、管理画面で「値も記録する」を外す。
 */
(function (global) {
  'use strict';

  // 保存先は利用者のトークンごとに分ける（同じ端末を複数人が使っても混ざらない）
  const S = () => global.IkenshoSession;
  const KEY = () => (S() ? S().key('ikensho.oplog.v1') : 'ikensho.oplog.v1');
  const OPT_KEY = 'ikensho.oplog.values.v1';   // 端末の設定なので分けない
  const LIMIT = 3000;          // 古いものから捨てる
  const DEBOUNCE = 900;        // 打ち込み中に1文字ずつ記録しない

  const LABEL = {
    read_start: '読み取り開始',
    read_done: '読み取り完了',
    read_error: '読み取り失敗',
    edit: '項目を修正',
    confirm: '確定',
    unconfirm: '確定を解除',
    clear_confirm: '削除して確定',
    confirm_group: 'まとめて確定',
    confirm_visible: '表示中をすべて確定',
    candidate: '候補を採用',
    hospital: '医療機関を一覧から選択',
    dictation: '音声入力',
    kana_fix: 'ふりがなを自動変換',
    llm_apply: 'LLMの候補を自動適用',
    anonymize: '匿名化表示',
    export: '書き出し',
    import: '取り込み',
    settings: '設定変更',
  };

  function nowIso() { return new Date().toISOString(); }

  function load() {
    try {
      const v = JSON.parse(localStorage.getItem(KEY()) || '[]');
      return Array.isArray(v) ? v : [];
    } catch (e) { return []; }
  }

  class OpLog {
    constructor() {
      this.entries = load();
      this.session = nowIso().slice(0, 19).replace(/[-:T]/g, '') + '-' +
        Math.random().toString(36).slice(2, 6);
      this._pending = new Map();
      this._before = new Map();
    }

    /** 値そのものを残すか（既定は残す）。 */
    get keepValues() {
      try { return localStorage.getItem(OPT_KEY) !== 'no'; } catch (e) { return true; }
    }
    set keepValues(v) {
      try { localStorage.setItem(OPT_KEY, v ? 'yes' : 'no'); } catch (e) { /* 無視 */ }
    }

    /** 値を文字列にする（記録用の整形前）。 */
    text(v) {
      if (v === null || v === undefined || v === '' || v === false) return '';
      if (v === true) return 'あり';
      if (Array.isArray(v)) return v.join('・');
      if (typeof v === 'object') {
        return [v.year, v.month, v.day].every(x => x == null)
          ? '' : `${v.year || '?'}/${v.month || '?'}/${v.day || '?'}`;
      }
      return String(v);
    }

    /** 何文字か。伏せ字にした欄でも増減を数えられるようにする。 */
    len(v) { return [...this.text(v)].length; }

    /** 記録して良い形に整える。個人情報の欄は文字数だけ。 */
    shape(v, pii) {
      const s = this.text(v);
      if (!s) return '';
      if (!this.keepValues || pii) return `（${[...s].length}文字）`;
      return [...s].length > 120 ? [...s].slice(0, 120).join('') + '…' : s;
    }

    add(action, detail) {
      const e = Object.assign({ t: nowIso(), session: this.session, action }, detail || {});
      this.entries.push(e);
      if (this.entries.length > LIMIT) this.entries.splice(0, this.entries.length - LIMIT);
      this.save();
      return e;
    }

    save() {
      try { localStorage.setItem(KEY(), JSON.stringify(this.entries)); }
      catch (e) {
        // 容量が足りない場合は半分捨てて入れ直す
        this.entries.splice(0, Math.floor(this.entries.length / 2));
        try { localStorage.setItem(KEY(), JSON.stringify(this.entries)); } catch (e2) { /* 諦める */ }
      }
    }

    /**
     * 項目の修正。打ち込みのたびに呼ばれるので、
     * 少し待って「打ち終わった値」を1件だけ残す。
     * 直す前の値は、その項目を最初に触った時点のものを使う。
     */
    edit(record, field, entry, beforeValue) {
      // 件ごとに分ける。混ざると、別の意見書の「直す前」と「直した後」が
      // 組み合わさった、存在しない訂正が記録されてしまう
      const key = (this.recordLabel(record) || '-') + '/' + field.id;
      if (!this._before.has(key)) this._before.set(key, beforeValue);
      const prev = this._pending.get(key);
      if (prev) clearTimeout(prev.timer);
      const emit = () => {
        this._pending.delete(key);
        const bv = this._before.get(key);
        const av = entry.date || entry.value;
        this._before.delete(key);
        if (this.text(bv) === this.text(av)) return;   // 元に戻した場合は記録しない
        this.add('edit', {
          record: this.recordLabel(record),
          field: field.id, label: field.label,
          before: this.shape(bv, field.pii), after: this.shape(av, field.pii),
          blen: this.len(bv), alen: this.len(av),
          conf: entry.confidence == null ? null : Math.round(entry.confidence * 100),
        });
      };
      this._pending.set(key, { timer: setTimeout(emit, DEBOUNCE), emit });
    }

    /** 打ちかけの修正を、書き出しや画面切り替えの前に確定させる。 */
    flush() {
      for (const [, p] of [...this._pending]) {
        clearTimeout(p.timer);
        p.emit();
      }
      this._pending.clear();
    }

    recordLabel(record) {
      if (!record) return '';
      // 内容とは無関係な目印だけを残す。ファイル名や氏名は入れない
      if (!record.id) {
        try {
          Object.defineProperty(record, 'id', {
            value: 'r' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6),
            enumerable: true, writable: true, configurable: true,
          });
        } catch (e) { return ''; }
      }
      return record.id;
    }

    /** 何をどれだけ直したかの要約。 */
    summary() {
      const s = {
        件数: 0, 読み取り: 0, 修正: 0, 確定: 0, 削除して確定: 0,
        候補採用: 0, 音声入力: 0, 書き出し: 0, 文字の増減: 0,
      };
      const fields = new Map();
      for (const e of this.entries) {
        s.件数++;
        if (e.action === 'read_done') s.読み取り += (e.count || 1);
        if (e.action === 'edit') {
          s.修正++;
          fields.set(e.label || e.field, (fields.get(e.label || e.field) || 0) + 1);
          const b = e.blen != null ? e.blen : [...(e.before || '')].length;
          const a = e.alen != null ? e.alen : [...(e.after || '')].length;
          s.文字の増減 += Math.abs(a - b);
        }
        if (e.action === 'confirm' || e.action === 'confirm_group' ||
            e.action === 'confirm_visible') s.確定 += (e.count || 1);
        if (e.action === 'clear_confirm') s.削除して確定++;
        if (e.action === 'candidate') s.候補採用++;
        if (e.action === 'dictation') s.音声入力++;
        if (e.action === 'export') s.書き出し++;
      }
      s.よく直した項目 = [...fields.entries()].sort((a, b) => b[1] - a[1]).slice(0, 8);
      return s;
    }

    label(action) { return LABEL[action] || action; }

    toCsv() {
      const head = ['日時', '操作', '対象', '項目', '直す前', '直した後', '確信度', '補足'];
      const cell = v => {
        const s = v === null || v === undefined ? '' : String(v);
        return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
      };
      const rows = this.entries.map(e => [
        e.t, this.label(e.action), e.record || '', e.label || e.field || '',
        e.before || '', e.after || '',
        e.conf == null ? '' : e.conf + '%', e.note || '',
      ].map(cell).join(','));
      return '﻿' + [head.join(','), ...rows].join('\r\n') + '\r\n';
    }

    toJson() {
      return JSON.stringify({
        generated_at: nowIso(),
        token: S() ? S().short() : null,
        values_recorded: this.keepValues,
        summary: this.summary(),
        entries: this.entries,
      }, null, 2);
    }

    clear() {
      this.entries = [];
      this.save();
    }
  }

  global.IkenshoOpLog = new OpLog();
  global.IkenshoOpLog.LABEL = LABEL;
})(window);
