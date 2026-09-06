/**
 * 記述欄の音声入力。
 *
 * 注意: ブラウザの音声認識（Web Speech API）を使う。
 * Chrome や Edge では**音声が製造元のサーバへ送られる**ため、
 * このアプリの他の処理（端末内で完結）とは扱いが違う。
 * 患者情報を口に出す前に、使ってよい環境か確かめてもらう必要があるので、
 * 初回に必ず確認を出す。
 */
(function (global) {
  'use strict';

  const CONSENT_KEY = 'ikensho.speech.consent.v1';
  const Rec = global.SpeechRecognition || global.webkitSpeechRecognition;

  function supported() {
    return !!Rec;
  }

  function consented() {
    try { return localStorage.getItem(CONSENT_KEY) === 'yes'; }
    catch (e) { return false; }
  }

  function askConsent() {
    if (consented()) return true;
    const ok = confirm(
      '音声入力について\n\n' +
      'この機能はブラウザの音声認識を使います。お使いのブラウザによっては、' +
      '話した音声が製造元のサーバへ送られます。\n' +
      '（読み取りそのものは端末内で完結しており、外部に送られません。' +
      '音声入力だけが例外です。）\n\n' +
      '患者情報を含む内容を話す場合は、所属の規程を確認してください。\n\n' +
      '音声入力を使いますか？');
    if (ok) {
      try { localStorage.setItem(CONSENT_KEY, 'yes'); } catch (e) { /* 保存できなくても続行 */ }
    }
    return ok;
  }

  class Dictation {
    constructor(opts) {
      this.onText = opts.onText || (() => {});
      this.onState = opts.onState || (() => {});
      this.rec = null;
      this.active = false;
      this.base = '';
    }

    start(currentText) {
      if (!supported() || this.active) return false;
      if (!askConsent()) return false;
      this.base = currentText || '';
      const rec = new Rec();
      rec.lang = 'ja-JP';
      rec.continuous = true;
      rec.interimResults = true;
      rec.maxAlternatives = 1;

      let settled = '';
      rec.onresult = ev => {
        let interim = '';
        for (let i = ev.resultIndex; i < ev.results.length; i++) {
          const r = ev.results[i];
          if (r.isFinal) settled += r[0].transcript;
          else interim += r[0].transcript;
        }
        const joiner = (this.base && !/[\s、。]$/.test(this.base)) ? '' : '';
        this.onText(this.base + joiner + settled + interim, !!interim);
      };
      rec.onerror = ev => {
        this.active = false;
        this.onState('error', ev.error === 'not-allowed'
          ? 'マイクの使用が許可されていません'
          : `音声認識のエラー: ${ev.error}`);
      };
      rec.onend = () => {
        this.active = false;
        this.onState('stopped', '');
      };
      this.rec = rec;
      this.active = true;
      this.onState('listening', '');
      try {
        rec.start();
      } catch (e) {
        this.active = false;
        this.onState('error', e.message);
        return false;
      }
      return true;
    }

    stop() {
      if (this.rec && this.active) {
        try { this.rec.stop(); } catch (e) { /* すでに止まっている */ }
      }
      this.active = false;
    }
  }

  global.IkenshoSpeech = { supported, Dictation, consented };
})(window);
