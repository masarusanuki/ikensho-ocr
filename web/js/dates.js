/**
 * 和暦の日付欄の解釈。
 * 「令和 7 年 3 月 20 日」から年・月・日を取り出し、
 * 確認画面では数字を埋めるだけで直せるようにする。
 */
(function (global) {
  'use strict';

  const ERAS = { 明治: 1868, 大正: 1912, 昭和: 1926, 平成: 1989, 令和: 2019 };
  const SHORT = { 明: '明治', 大: '大正', 昭: '昭和', 平: '平成', 令: '令和',
                  M: '明治', T: '大正', S: '昭和', H: '平成', R: '令和' };
  const ERA_LIST = Object.keys(ERAS);

  function toHalf(s) {
    return String(s || '').replace(/[！-～]/g,
      c => String.fromCharCode(c.charCodeAt(0) - 0xFEE0)).replace(/　/g, ' ');
  }

  function canonicalEra(era) {
    const t = toHalf(era).trim();
    if (!t) return '';
    if (ERAS[t]) return t;
    return SHORT[t] || '';
  }

  /** 文字列を年・月・日に分ける。取れたものだけ返す。 */
  function parse(text) {
    const out = { era: '', year: null, month: null, day: null };
    if (!text) return out;
    let t = toHalf(text);
    const m = t.match(/(明治|大正|昭和|平成|令和|明|大|昭|平|令)/);
    if (m) { out.era = canonicalEra(m[1]); t = t.slice(m.index + m[1].length); }
    // 印刷されている「年」「月」「日」を区切りにして拾う（Python の dates.py と同じ規則）。
    //
    // 「日」は欄のいちばん右に印刷されているため、読み取りの都合で落ちることがある
    // （例: `12年3月4`）。そこで **「日」が無くても「月」より後の数字を日として拾う**。
    // 逆に `8日年11月20` のように余分な字が挟まることもあるので、少しの異物を許す。
    const y = t.match(/(\d+)\D{0,2}年/);
    if (y) out.year = parseInt(y[1], 10);
    const afterYear = y ? t.slice(y.index + y[0].length) : t;

    const mo = afterYear.match(/(\d+)\D{0,2}月/);
    if (mo) out.month = parseInt(mo[1], 10);
    // 「月」の位置で切る。月の数字が読めなくても、その後ろは日として拾える
    const mark = afterYear.indexOf('月');
    const afterMonth = mark >= 0 ? afterYear.slice(mark + 1) : null;

    if (afterMonth !== null) {
      const d = afterMonth.match(/(\d+)/);          // 「日」が無くても拾う
      if (d) out.day = parseInt(d[1], 10);
    } else {
      const d = t.match(/(\d+)\D{0,2}日/);
      if (d) out.day = parseInt(d[1], 10);
    }

    if (out.year === null && out.month === null && out.day === null) {
      const nums = (t.match(/\d{1,4}/g) || []).map(n => parseInt(n, 10));
      ['year', 'month', 'day'].forEach((k, i) => { if (nums[i] !== undefined) out[k] = nums[i]; });
    }
    // ありえない値は捨てる（読み間違いをそのまま通さない）。
    // 元号年なので、年は2桁までしか入らない
    if (out.year !== null && !(out.year >= 1 && out.year <= 99)) out.year = null;
    if (out.month !== null && !(out.month >= 1 && out.month <= 12)) out.month = null;
    if (out.day !== null && !(out.day >= 1 && out.day <= 31)) out.day = null;
    return out;
  }

  /** 部品から「7年3月20日」に戻す。空の部分は飛ばす。 */
  function format(parts, withEra) {
    if (!parts) return '';
    let s = '';
    if (withEra && parts.era) s += parts.era;
    for (const [k, mark] of [['year', '年'], ['month', '月'], ['day', '日']]) {
      const v = parts[k];
      if (v !== null && v !== undefined && v !== '') s += `${v}${mark}`;
    }
    return s;
  }

  /** 元号と和暦年から西暦を作る。判断できなければ null。 */
  function toGregorian(era, year, month, day) {
    const base = ERAS[canonicalEra(era)];
    if (!base || !year || year < 1) return null;
    const y = base + Number(year) - 1;
    if (y < 1868 || y > 2200) return null;
    const p = n => String(n).padStart(2, '0');
    if (month && day) return `${y}-${p(month)}-${p(day)}`;
    if (month) return `${y}-${p(month)}`;
    return String(y);
  }

  /**
   * fixedEra=true のときは、本文中に元号らしき文字があっても無視して
   * 渡された元号を使う（様式に印刷されている場合）。
   */
  function enrich(value, era, fixedEra) {
    const parts = parse(value);
    if (fixedEra && era) parts.era = canonicalEra(era);
    else if (era && !parts.era) parts.era = canonicalEra(era);
    return {
      parts: { year: parts.year, month: parts.month, day: parts.day },
      era: parts.era,
      text: format(parts),
      gregorian: toGregorian(parts.era, parts.year, parts.month, parts.day),
    };
  }

  global.IkenshoDates = { parse, format, toGregorian, enrich, canonicalEra, ERA_LIST };
})(window);
