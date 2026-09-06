/**
 * 利用者の区別（端末ごとのトークン）。
 *
 * 読み取った内容も操作ログも、このブラウザの中だけに保存する。
 * ただし同じ端末を複数の人が使うと履歴が混ざるので、
 * ブラウザごとに発行したトークンで保存先を分ける。
 *
 * - トークンは初回に自動で発行する（サーバには送らない）
 * - 「新しく発行」すると、それまでの履歴からは切り離される
 *   （消してはいないが、元のトークンを入れ直さない限り見えない）
 * - 別の端末で続きをする場合は、トークンを入れ直す
 */
(function (global) {
  'use strict';

  const TOKEN_KEY = 'ikensho.token.v1';
  const LEGACY = {           // トークン導入前の保存先。初回に移し替える
    'ikensho.records.v1': true,
    'ikensho.settings.v1': true,
    'ikensho.oplog.v1': true,
  };

  function issue() {
    const b = new Uint8Array(12);
    (global.crypto || {}).getRandomValues
      ? global.crypto.getRandomValues(b)
      : b.forEach((_, i) => { b[i] = Math.floor(Math.random() * 256); });
    return [...b].map(x => x.toString(16).padStart(2, '0')).join('');
  }

  function valid(t) { return /^[0-9a-f]{8,64}$/.test(String(t || '').trim()); }

  class Session {
    constructor() {
      let t = null;
      try { t = localStorage.getItem(TOKEN_KEY); } catch (e) { /* 使えない環境 */ }
      if (!valid(t)) {
        t = issue();
        try { localStorage.setItem(TOKEN_KEY, t); } catch (e) { /* 保存できなくても続行 */ }
        this.fresh = true;
      }
      this.token = t;
      this.migrate();
    }

    /** 保存先の名前。トークンごとに分ける。 */
    key(base) { return `${base}.${this.token}`; }

    short() { return this.token.slice(0, 8); }

    /** トークン導入前のデータを、今のトークンの下へ移す（1度だけ）。 */
    migrate() {
      try {
        for (const base of Object.keys(LEGACY)) {
          const old = localStorage.getItem(base);
          if (old === null) continue;
          if (localStorage.getItem(this.key(base)) === null) {
            localStorage.setItem(this.key(base), old);
          }
          localStorage.removeItem(base);
        }
      } catch (e) { /* 使えない環境では何もしない */ }
    }

    /** 新しいトークンを発行する。それまでの履歴は見えなくなる。 */
    reissue() {
      const t = issue();
      try { localStorage.setItem(TOKEN_KEY, t); } catch (e) { /* 無視 */ }
      this.token = t;
      return t;
    }

    /** 別の端末で使っていたトークンに切り替える。 */
    use(t) {
      t = String(t || '').trim().toLowerCase();
      if (!valid(t)) throw new Error('トークンの形式が正しくありません（16進数の文字列）');
      try { localStorage.setItem(TOKEN_KEY, t); } catch (e) { /* 無視 */ }
      this.token = t;
      return t;
    }

    /** この端末に残っているトークンの一覧（保存先の名前から拾う）。 */
    known() {
      const found = new Set();
      try {
        for (let i = 0; i < localStorage.length; i++) {
          const m = /^ikensho\.records\.v1\.([0-9a-f]{8,64})$/.exec(localStorage.key(i));
          if (m) found.add(m[1]);
        }
      } catch (e) { /* 無視 */ }
      found.add(this.token);
      return [...found];
    }
  }

  global.IkenshoSession = new Session();
})(window);
