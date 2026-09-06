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

    /**
     * トークン導入前のデータを、今のトークンの下へ移す（1度だけ）。
     * 共用端末では前の利用者の記録を引き継ぐことになるので、
     * 引き継いだ場合は `migrated` を立てて画面に知らせる。
     */
    migrate() {
      try {
        for (const base of Object.keys(LEGACY)) {
          const old = localStorage.getItem(base);
          if (old === null) continue;
          if (localStorage.getItem(this.key(base)) === null) {
            localStorage.setItem(this.key(base), old);
            this.migrated = true;
          }
          localStorage.removeItem(base);
        }
      } catch (e) { /* 使えない環境では何もしない */ }
    }

    /** localStorage が使えるか（使えないと保存は全部失敗する）。 */
    get storable() {
      try {
        localStorage.setItem('ikensho.probe', '1');
        localStorage.removeItem('ikensho.probe');
        return true;
      } catch (e) { return false; }
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

    /**
     * この端末に残っている「今の自分以外」の記録の数。
     * トークン文字列そのものは返さない（返すと他人の記録を開けてしまう）。
     */
    otherCount() {
      const found = new Set();
      try {
        for (let i = 0; i < localStorage.length; i++) {
          const m = /^ikensho\.(?:records|oplog|settings)\.v1\.([0-9a-f]{8,64})$/
            .exec(localStorage.key(i));
          if (m && m[1] !== this.token) found.add(m[1]);
        }
      } catch (e) { /* 無視 */ }
      return found.size;
    }

    /**
     * この端末に残っている、今のトークン以外の記録をすべて消す。
     * 共用端末で作業を終えるときに使う。消したら元に戻せない。
     */
    clearOthers() {
      const keys = [];
      try {
        for (let i = 0; i < localStorage.length; i++) {
          const k = localStorage.key(i);
          const m = /^ikensho\.(records|oplog|settings)\.v1\.([0-9a-f]{8,64})$/.exec(k);
          if (m && m[2] !== this.token) keys.push(k);
        }
        keys.forEach(k => localStorage.removeItem(k));
      } catch (e) { /* 無視 */ }
      return keys.length;
    }
  }

  global.IkenshoSession = new Session();
})(window);
