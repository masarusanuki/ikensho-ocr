/**
 * 欄の答えを「人が読む形」にそろえる。Python 版 `answers.py` と対にして直すこと。
 *
 * 出力は JSON・CSV・Markdown の3通りあるが、**同じ欄が出力ごとに違う答えに
 * 見えてはいけない**。読み方を決めるのはこのファイル1か所だけにする。
 *
 * **選択肢に付いている記入欄。** 様式には「その他（　　　）」のように、
 * 印だけでは中身の分からない選択肢がある。診療科がその代表で、
 * 13個の選択肢に収まらない科は「その他」に名前が書かれる。
 *
 *   - 「その他」で始まる選択肢 … 言葉に中身が無いので、**書かれた名前で置き換える**
 *   - それ以外 … 言葉に意味があるので、**括弧で足す**（`血圧` → `血圧（140/90）`）
 *
 * どの選択肢にどの記入欄が付いているかは項目定義の `optionTexts`
 * （`tools/form_definition.py` が正典）。
 */
(function (global) {
  'use strict';

  const REPLACE_PREFIX = 'その他';   // 言葉に中身が無く、記入欄の内容で置き換える選択肢
  const FLAG_KEY = '該当';           // flag 型（単独の□）で、印が付いたときの鍵

  function linksOf(f) {
    return f.optionTexts || f.option_texts || {};
  }

  function textOf(fields, fid) {
    if (!fid) return '';
    const e = fields[fid];
    if (!e) return '';
    const v = e.value;
    if (v === null || v === undefined || v === false) return '';
    return String(v).trim();
  }

  /** 選択肢の言葉に、付属の記入欄の中身を反映した言葉を返す。 */
  function decorate(word, text) {
    if (!text) return word;
    if (String(word).startsWith(REPLACE_PREFIX)) return text;
    return `${word}（${text}）`;
  }

  /** その欄の選択肢を、付属の記入欄まで含めた言葉で並べる。 */
  function optionWords(fields, schema, f) {
    const e = fields[f.id] || {};
    let words = e.optionWords || e.option_words;
    const opts = f.options || [];
    if (!(Array.isArray(words) && words.length === opts.length)) {
      words = opts.map(String);
    }
    const links = linksOf(f);
    return opts.map((base, i) => decorate(words[i], textOf(fields, links[String(base)])));
  }

  /** その欄の答えを、人が読む形で返す。 */
  function resolve(fields, schema, f) {
    const e = fields[f.id];
    if (!e) return null;
    const value = e.value;
    const links = linksOf(f);

    if (f.type === 'flag') {
      if (!value) return value === undefined ? null : value;
      const text = textOf(fields, links[FLAG_KEY]);
      return text ? `${FLAG_KEY}（${text}）` : value;
    }
    if (!f.options) return value === undefined ? null : value;

    // 読み取った値は**実物の言葉**に置き換え済みなので、
    // 定義の選択肢と読んだ言葉の両方から、付属欄の相手を引けるようにする
    const done = optionWords(fields, schema, f);
    const plain = (f.options || []).map(String);
    const table = {};
    const src = e.optionWords || e.option_words;
    if (Array.isArray(src) && src.length === plain.length) {
      plain.forEach((base, i) => { table[String(src[i])] = done[i]; table[base] = done[i]; });
    } else {
      plain.forEach((base, i) => { table[base] = done[i]; });
    }
    if (Array.isArray(value)) return value.map(v => table[String(v)] || String(v));
    if (typeof value === 'string') return table[value] || value;
    return value === undefined ? null : value;
  }

  /** 選択肢に付いている記入欄の一覧（欄id → 付いている選択肢の欄id）。 */
  function usedTextFields(schema) {
    const out = {};
    for (const sec of (schema.sections || [])) {
      for (const f of (sec.fields || [])) {
        const links = linksOf(f);
        for (const k of Object.keys(links)) out[String(links[k])] = f.id;
      }
    }
    return out;
  }

  global.IkenshoAnswers = { resolve, optionWords, decorate, usedTextFields,
                            REPLACE_PREFIX, FLAG_KEY };
})(window);
