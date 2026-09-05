/**
 * 匿名化加工済みデータ（研究用）の取り扱い。
 *
 * 研究用に配布される意見書は氏名欄が白抜き（黒塗り）されていることがある。
 * その場合は「読み取り失敗」ではなく「匿名化済み」として扱い、
 * 住所・連絡先などの個人を特定しうる欄は「マスク済み」と表示する。
 * 元の読み取り値は破棄するため、出力に個人情報が残らない。
 */
(function (global) {
  'use strict';

  const ANONYMIZED = '匿名化済み';
  const MASKED = 'マスク済み';

  const isBlank = v =>
    v === null || v === undefined || (typeof v === 'string' && !v.trim());

  /** 氏名欄がすべて空なら、匿名化済みデータの可能性が高い。 */
  function looksAnonymized(record, schema) {
    const names = schema.order.filter(id => schema.byId[id].pii === 'name');
    if (!names.length) return false;
    return names.every(id => isBlank((record.fields[id] || {}).value));
  }

  /**
   * 匿名化データとして項目を書き換える。
   * force=false … 氏名欄が空の場合だけ「匿名化済み」にする
   * force=true  … 住所・連絡先なども一律で「マスク済み」にする
   */
  function apply(record, schema, force) {
    let changed = 0;
    for (const id of schema.order) {
      const f = schema.byId[id];
      if (!f.pii) continue;
      const e = record.fields[id];
      if (!e) continue;
      if (f.pii === 'name') {
        if (!force && !isBlank(e.value)) continue;
        e.value = ANONYMIZED;
      } else if (f.pii === 'mask') {
        if (!force) continue;
        e.value = MASKED;
      } else continue;
      e.raw = '';
      e.candidates = [];
      e.confidence = 1;
      e.level = 'high';
      e.anonymized = true;
      e.edited = false;
      changed++;
    }
    if (changed) record.anonymized = true;
    return changed;
  }

  /** 匿名化済みの項目を元の読み取り値には戻せないため、解除は表示だけ戻す。 */
  function clear(record, schema) {
    for (const id of schema.order) {
      const e = record.fields[id];
      if (e && e.anonymized) {
        e.anonymized = false;
        e.confidence = 0;
        e.level = 'low';
        e.value = '';
      }
    }
    record.anonymized = false;
  }

  global.IkenshoAnonymize = { apply, clear, looksAnonymized, ANONYMIZED, MASKED };
})(window);
