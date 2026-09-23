/** 読み取り結果の JSON / CSV 出力。Python 版と同じ列構成にそろえている。 */
(function (global) {
  'use strict';

  function download(filename, text, mime) {
    const blob = new Blob([text], { type: mime || 'application/octet-stream' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = filename;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function stamp() {
    const d = new Date(), p = n => String(n).padStart(2, '0');
    return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}_${p(d.getHours())}${p(d.getMinutes())}`;
  }

  /**
   * 機械学習や集計に使いやすい形の値を導く。
   * 和暦のままでは比較できないので、西暦に直したものを別に持つ。
   */
  function buildDerived(rec, schema) {
    const out = {};
    for (const id of schema.order) {
      if (!(id.startsWith('diagnosis') && id.endsWith('_name'))) continue;
      const e = rec.fields[id] || {};
      out[`${id}_icd10`] = e.icd10 || null;
      out[`${id}_tokutei`] = e.tokutei === undefined ? null : e.tokutei;
    }
    for (const id of schema.order) {
      const f = schema.byId[id];
      if (f.kind !== 'date_wareki') continue;
      const e = rec.fields[id] || {};
      const d = e.date || {};
      out[`${id}_iso`] = e.gregorian || null;
      out[`${id}_era`] = e.era || '';
      out[`${id}_year`] = d.year === undefined ? null : d.year;
      out[`${id}_month`] = d.month === undefined ? null : d.month;
      out[`${id}_day`] = d.day === undefined ? null : d.day;
    }
    const full = s => (s && s.length === 10) ? new Date(s + 'T00:00:00') : null;
    const birth = full(out.birth_date_iso);
    // 年月日がそろっている方を使う（片方が欠けていても計算できるように）
    const at = full(out.entry_date_iso) || full(out.last_exam_date_iso);
    let computed = null;
    if (birth && at) {
      let y = at.getFullYear() - birth.getFullYear();
      if (at.getMonth() < birth.getMonth() ||
          (at.getMonth() === birth.getMonth() && at.getDate() < birth.getDate())) y--;
      if (y >= 0 && y <= 130) computed = y;
    }
    const raw = (rec.fields.age || {}).value;
    const m = raw === null || raw === undefined ? null : String(raw).match(/\d+/);
    const written = m ? parseInt(m[0], 10) : null;
    out.age_computed = computed;
    out.age_written = written;
    out.age_matches = (computed === null || written === null)
      ? null : Math.abs(computed - written) <= 1;
    return out;
  }

  function derivedKeys(schema) {
    const keys = [];
    for (const id of schema.order) {
      if (schema.byId[id].kind === 'date_wareki') {
        keys.push(`${id}_iso`, `${id}_era`, `${id}_year`, `${id}_month`, `${id}_day`);
      }
    }
    // 診断名に当てた ICD（Python の derive.derived_keys と同じ並び：日付のあと）
    for (const id of schema.order) {
      if (id.startsWith('diagnosis') && id.endsWith('_name')) {
        keys.push(`${id}_icd10`, `${id}_tokutei`);
      }
    }
    return keys.concat(['age_computed', 'age_written', 'age_matches']);
  }

  function derivedLabels(schema) {
    const labels = {};
    for (const id of schema.order) {
      const f = schema.byId[id];
      if (f.kind !== 'date_wareki') continue;
      labels[`${id}_iso`] = `${f.label}（西暦）`;
      labels[`${id}_era`] = `${f.label}（元号）`;
      labels[`${id}_year`] = `${f.label}（和暦年）`;
      labels[`${id}_month`] = `${f.label}（月）`;
      labels[`${id}_day`] = `${f.label}（日）`;
    }
    for (const id of schema.order) {
      if (!(id.startsWith('diagnosis') && id.endsWith('_name'))) continue;
      const f = schema.byId[id];
      labels[`${id}_icd10`] = `${f.label}（ICD10）`;
      labels[`${id}_tokutei`] = `${f.label}（特定疾病）`;
    }
    labels.age_computed = '年齢（生年月日から計算）';
    labels.age_written = '年齢（様式の記載）';
    labels.age_matches = '年齢の一致';
    return labels;
  }

  function flatAny(v) {
    if (v === null || v === undefined) return '';
    if (Array.isArray(v)) return v.join('；');
    if (typeof v === 'boolean') return v ? '該当' : '';
    return String(v);
  }

  function flatValue(entry) {
    const v = entry ? entry.value : null;
    if (v === null || v === undefined) return '';
    if (Array.isArray(v)) return v.join('；');
    if (typeof v === 'boolean') return v ? '該当' : '';
    return String(v);
  }

  /** 1件分を、保存用の素直な形にする。 */
  function toRecordJson(rec, schema) {
    const values = {}, meta = {}, answers = {};
    for (const id of schema.order) {
      const e = rec.fields[id];
      if (!e) continue;
      values[id] = e.value === undefined ? null : e.value;
      answers[id] = global.IkenshoAnswers.resolve(rec.fields, schema, schema.byId[id]);
      meta[id] = {
        label: e.label, type: e.type, section: e.section, page: e.page,
        confidence: e.confidence, level: e.level,
        edited: !!e.edited, confirmed: !!e.confirmed, anonymized: !!e.anonymized,
        raw: e.raw === undefined ? null : e.raw,
        date: e.date || null, era: e.era || '', gregorian: e.gregorian || null,
        // なぜ確信度が低いのかが分かるよう、注記と訂正も残す。
        // これが無いと、書き出して読み直したときに理由だけが消える
        note: e.note || '',
        // 診断名に当てた ICD（近い分類の場合もある）
        icd10: e.icd10 || null, icd_name: e.icd_name || null,
        tokutei: e.tokutei === undefined ? null : e.tokutei,
        corrections: e.corrections || [],
        expected_chars: e.expected_chars === undefined ? null : e.expected_chars,
        llm_applied: !!e.llm_applied,
      };
    }
    return {
      schema_version: schema.version,
      form_name: schema.formName,
      template_id: rec.templateId,
      ocr_engine: rec.ocrEngine || 'none',
      anonymized: !!rec.anonymized,
      read_at: rec.readAt,
      sources: rec.pages.map(p => ({
        source: p.source, source_page: p.sourcePage,
        page_index: p.pageIndex, matched: p.matched,
        score: p.score, dewarped: p.dewarped,
      })),
      warnings: rec.warnings || [],
      // 実物の様式と定義の食い違い（ブラウザ版には見張りが無いので常に空）
      form_drift: (rec.formDrift || []).map(d => ({
        field: d.field, label: d.label,
        missing: d.missing || [], extra: d.extra || [], row: d.row })),
      values,
      // values は**選択肢の言葉**。answers は「その他（　）」に書かれた中身まで
      // 含めた、人が読む形（診療科の「その他」は書かれた名前そのものになる）
      answers,
      // 機械学習や集計に使いやすい形（西暦に直した日付など）
      derived: buildDerived(rec, schema),
      meta,
    };
  }

  function exportJson(records, schema, filename) {
    const payload = {
      exported_at: new Date().toISOString(),
      schema_version: schema.version,
      count: records.length,
      records: records.map(r => toRecordJson(r, schema)),
    };
    download(filename || `ikensho_${stamp()}.json`,
             JSON.stringify(payload, null, 2), 'application/json;charset=utf-8');
  }

  function csvEscape(s) {
    s = s === null || s === undefined ? '' : String(s);
    return /[",\n\r]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
  }

  /**
   * CSV は「1行=1件」。各項目について値と確信度の2列を出す。
   * Excel で開けるよう BOM 付き UTF-8 にする。
   */
  function exportCsv(records, schema, filename) {
    const dkeys = derivedKeys(schema);
    const dlabels = derivedLabels(schema);
    const head = ['record_no', 'template_id', 'read_at', 'anonymized', 'sources', 'warnings'];
    for (const id of schema.order) head.push(`${id}`, `${id}__confidence`);
    head.push(...dkeys);
    const labelRow = ['#', '様式', '読取日時', '匿名化', '元ファイル', '警告'];
    for (const id of schema.order) labelRow.push(schema.byId[id].label, '確信度');
    labelRow.push(...dkeys.map(k => dlabels[k] || k));
    const lines = [head.map(csvEscape).join(','), labelRow.map(csvEscape).join(',')];
    records.forEach((rec, i) => {
      const row = [
        i + 1, rec.templateId || '', rec.readAt || '',
        rec.anonymized ? 'はい' : 'いいえ',
        [...new Set(rec.pages.map(p => p.source))].join('；'),
        (rec.warnings || []).join('；'),
      ];
      for (const id of schema.order) {
        const e = rec.fields[id];
        // JSON の answers と同じ読み方にする。CSV だけ「その他」のままだと
        // 同じ読み取りが出力ごとに違って見えてしまう
        row.push(e ? flatAny(global.IkenshoAnswers.resolve(rec.fields, schema, schema.byId[id]))
                   : '', e ? e.confidence : '');
      }
      const d = buildDerived(rec, schema);
      for (const k of dkeys) {
        const v = d[k];
        row.push(v === null || v === undefined ? ''
                 : (v === true ? '1' : (v === false ? '0' : v)));
      }
      lines.push(row.map(csvEscape).join(','));
    });
    download(filename || `ikensho_${stamp()}.csv`,
             '﻿' + lines.join('\r\n'), 'text/csv;charset=utf-8');
  }

  /** 保存した JSON を読み戻す。 */
  function importJson(payload, schema) {
    const out = [];
    for (const r of (payload.records || [])) {
      const fields = {};
      for (const id of schema.order) {
        const f = schema.byId[id];
        const m = (r.meta || {})[id] || {};
        fields[id] = {
          value: (r.values || {})[id] === undefined ? null : r.values[id],
          confidence: m.confidence || 0, level: m.level || 'low',
          edited: !!m.edited, confirmed: !!m.confirmed,
          anonymized: !!m.anonymized, raw: m.raw || '',
          date: m.date || null, era: m.era || '', gregorian: m.gregorian || null,
          note: m.note || '', corrections: m.corrections || [],
          expected_chars: m.expected_chars === undefined ? null : m.expected_chars,
          llm_applied: !!m.llm_applied,
          kind: f.kind || '',
          label: f.label, type: f.type, section: f.sectionTitle, page: f.page,
          options: f.options,
        };
      }
      out.push({
        // 取り込んだ件にも目印を付ける（操作ログを件ごとに分けるため）
        id: 'i' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6),
        fields, templateId: r.template_id, ocrEngine: r.ocr_engine,
        anonymized: !!r.anonymized,
        readAt: r.read_at, warnings: r.warnings || [], images: {},
        pages: (r.sources || []).map(s => ({
          source: s.source, sourcePage: s.source_page, pageIndex: s.page_index,
          matched: s.matched, score: s.score, dewarped: s.dewarped,
        })),
      });
    }
    return out;
  }


  // ------------------------------------------- 様式の形そのままのJSON
  // Python 版 `export.py::record_to_form_json` と同じ形にそろえている。

  // 項目の種類を、様式を見ている人に分かる言葉にする
  const KIND_JA = {
    text: '記述', textarea: '記述（複数行）', choice: '択一',
    multi: '複数選択', circle: '丸囲み', flag: '有無',
  };
  const LEVEL_JA = { high: '高', medium: '中', low: '低', edited: '修正', done: '確定' };

  /** 選択肢の言葉。実物を OCR で読んだ／管理画面で直したものを優先する。 */
  function optionWords(entry, f) {
    const w = entry.optionWords || entry.option_words;
    if (Array.isArray(w) && w.length === (f.options || []).length) return w.map(String);
    return (f.options || []).map(String);
  }

  /**
   * 様式の1項目を、そのまま読める形にする。
   * チェック欄は**言葉**が要なので、選択肢の言葉と、どれに印が付いたかを返す。
   */
  function formItem(entry, f, fields, schema) {
    const A = global.IkenshoAnswers;
    const item = { 項目: f.label, 種類: KIND_JA[f.type] || f.type,
                   答え: A.resolve(fields, schema, f),
                   値: entry.value === undefined ? null : entry.value };
    const links = f.optionTexts || f.option_texts || {};
    if (f.type === 'flag' && links[A.FLAG_KEY]) {
      const note = (fields[links[A.FLAG_KEY]] || {}).value;
      if (note) item['内容'] = note;
    }
    if (f.options) {
      const words = optionWords(entry, f);
      item['選択肢'] = words;
      const detail = entry.detail || [];
      const picked = entry.value;
      const chosen = new Set(Array.isArray(picked) ? picked
                             : (typeof picked === 'string' ? [picked] : []));
      const marks = words.map((word, i) => {
        const d = detail.find(x => x.opt === i) || {};
        const m = { 言葉: word, 印: !!d.checked || chosen.has(word) };
        // 「その他（　　）」のように、選択肢に記入欄が付いていることがある
        const note = (fields[links[String((f.options || [])[i])]] || {}).value;
        if (note) m['内容'] = note;
        if (d.struck) m['二重線で訂正'] = true;
        if (d.circled) m['丸囲み'] = true;
        return m;
      });
      if (marks.length) item['チェック'] = marks;
      if (entry.optionWords || entry.option_words) {
        item['定義の選択肢'] = (f.options || []).map(String);
      }
    }
    if (f.kind === 'date_wareki') {
      item['西暦'] = entry.gregorian || null;
      if (entry.era) item['元号'] = entry.era;
    }
    if (entry.icd10) {
      item['ICD10'] = entry.icd10;
      if (entry.icd_name && entry.icd_name !== entry.value) item['ICDの分類名'] = entry.icd_name;
      if (entry.tokutei) item['特定疾病'] = true;
    }
    item['確信度'] = entry.confidence === undefined ? null : entry.confidence;
    item['確信度の段階'] = LEVEL_JA[entry.level] || entry.level || null;
    if (entry.confirmed) item['確認済み'] = true;
    if (entry.edited) item['人が直した'] = true;
    if (entry.note) item['注記'] = entry.note;
    for (const n of (entry.labelNotes || entry.label_notes || [])) {
      if (!n.changed) continue;
      item['言葉の食い違い'] = item['言葉の食い違い'] || [];
      item['言葉の食い違い'].push({ 定義: n.expected, 読めた言葉: n.read });
    }
    item['項目ID'] = f.id;
    return item;
  }

  /**
   * 様式（PDF）の並びそのままの JSON。
   * 節 → まとまり → 項目 の順に入れ子にしてあり、上から読めば様式と同じ順になる。
   */
  function toFormJson(rec, schema) {
    const sections = [];
    for (const sec of (schema.sections || [])) {
      const items = [];
      const groups = {};
      const pages = new Set();
      for (const sf of (sec.fields || [])) {
        const f = schema.byId[sf.id];
        const entry = rec.fields[sf.id];
        if (!f || !entry) continue;
        pages.add(f.page);
        const item = formItem(entry, f, rec.fields, schema);
        const gid = f.group || f.groupId;
        if (gid) {
          let g = groups[gid];
          if (!g) {
            g = { まとまり: f.groupLabel || f.group_label || gid, 項目: [] };
            groups[gid] = g;
            items.push(g);
          }
          g['項目'].push(item);
        } else {
          items.push(item);
        }
      }
      if (!items.length) continue;
      sections.push({ 表題: sec.title || sec.id,
                      ページ: pages.size ? Math.min(...pages) : null,
                      項目: items });
    }
    return {
      様式: schema.formName,
      様式ID: rec.templateId,
      定義の版: schema.version,
      読取日時: rec.readAt || new Date().toISOString(),
      読み取りに使ったOCR: rec.ocrEngine || 'none',
      匿名化済み: !!rec.anonymized,
      元ファイル: (rec.pages || []).map(p => ({
        ファイル: p.source, ページ: p.sourcePage,
        様式のページ: p.pageIndex, 判別できた: p.matched })),
      注意: rec.warnings || [],
      // 実物の様式と定義の食い違い。ブラウザ版には見張り（pagequest）が無いので
      // 常に空だが、**Python版と形を揃える**ために出す
      様式の食い違い: (rec.formDrift || []).map(d => ({
        項目: d.label, 項目ID: d.field,
        定義にあって読めなかった言葉: d.missing || [],
        実物にあって定義に無い言葉: d.extra || [],
        読めた行: d.row })),
      節: sections,
    };
  }

  function exportFormJson(records, schema, filename) {
    const payload = {
      書き出し日時: new Date().toISOString(),
      件数: records.length,
      意見書: records.map(r => toFormJson(r, schema)),
    };
    download(filename || `ikensho_様式の形_${stamp()}.json`,
             JSON.stringify(payload, null, 2), 'application/json;charset=utf-8');
  }

  // -------------------------------------------------------------------------
  // Markdown。**そのまま読ませられる文書**にする。Python 版 export.py と対。
  // -------------------------------------------------------------------------
  const MD_LOW = 0.80;          // これより下は「要確認」の印を付ける
  const MD_MARK = '⚠';
  const MD_EMPTY = '（空欄）';   // 行の抜けと取り違えられないようにする
  const MD_LLM = '✎';           // LLM が読み崩れを直した欄。**直したことを隠さない**

  function mdCell(value) {
    if (value === null || value === undefined || value === false) return '';
    if (value === true) return '該当';
    if (Array.isArray(value)) value = value.filter(v => String(v) !== '').join('、');
    return String(value).replace(/\|/g, '｜').replace(/\n/g, ' ').trim();
  }

  function mdLevel(entry) {
    const lv = LEVEL_JA[entry.level] || entry.level || '';
    let mark = entry.llm_applied ? MD_LLM : '';
    if (entry.confidence === null || entry.confidence === undefined) return `${lv}${mark}`.trim();
    if (entry.confidence < MD_LOW && entry.level !== 'edited' && entry.level !== 'done') {
      mark = MD_MARK + mark;
    }
    return `${lv} ${entry.confidence.toFixed(2)}${mark}`.trim();
  }

  /** 表に入れる答え。日付は西暦も添える（和暦だけでは比べられないため）。 */
  function mdAnswer(rec, schema, f, entry) {
    let ans = mdCell(global.IkenshoAnswers.resolve(rec.fields, schema, f));
    if (!ans) return MD_EMPTY;
    if (f.kind === 'date_wareki') {
      const era = entry.era || '';
      if (era && ans.indexOf(era) !== 0) ans = era + ans;
      if (entry.gregorian) ans = `${ans}（${entry.gregorian}）`;
    }
    return ans;
  }

  function toMarkdown(rec, schema) {
    const A = global.IkenshoAnswers;
    const absorbed = A.usedTextFields(schema);
    const out = [];
    out.push(`# ${schema.formName} 読み取り結果`, '');
    out.push('これは紙の主治医意見書を OCR で読み取った結果です。' +
             '**読み取りには誤りが含まれます。**');
    out.push(`確信度が ${MD_LOW.toFixed(2)} 未満の欄には ${MD_MARK} を、` +
             `読み崩れをLLMが直した欄には ${MD_LLM} を付けてあります。` +
             '原本と照らして確かめてください。', '');
    out.push(`- 様式: ${rec.templateId || '不明'}`);
    out.push(`- 読み取り日時: ${rec.readAt || new Date().toISOString()}`);
    out.push(`- 読み取りに使った OCR: ${rec.ocrEngine || 'none'}`);
    if (rec.anonymized) out.push('- **匿名化加工済み**（氏名・住所・連絡先はマスクしてあります）');
    out.push('');

    for (const sec of (schema.sections || [])) {
      const rows = [];
      for (const sf of (sec.fields || [])) {
        const f = schema.byId[sf.id];
        const e = f && rec.fields[sf.id];
        if (!f || !e) continue;
        if (absorbed[sf.id]) continue;   // 答えの中に出ているので繰り返さない
        rows.push(`| ${mdCell(f.label)} | ${mdAnswer(rec, schema, f, e)} | ${mdLevel(e)} |`);
      }
      if (!rows.length) continue;
      out.push(`## ${sec.title || sec.id}`, '', '| 項目 | 答え | 確信度 |', '|---|---|---|');
      out.push.apply(out, rows);
      out.push('');
    }

    // 空欄で確信度が低いものまで並べると埋もれるので、**読めた値があるもの**だけ
    const check = schema.order.map(id => schema.byId[id]).filter(f => {
      const e = rec.fields[f.id];
      if (!e || e.confidence === null || e.confidence === undefined) return false;
      if (e.confidence >= MD_LOW || e.level === 'edited' || e.level === 'done') return false;
      return !!mdCell(A.resolve(rec.fields, schema, f));
    });
    if (check.length) {
      out.push('## 確かめてほしいところ', '');
      for (const f of check) {
        const e = rec.fields[f.id];
        const extra = [];
        if (e.raw && e.raw !== String(e.value === undefined ? '' : e.value)) {
          extra.push(`OCRの生読み「${mdCell(e.raw)}」`);
        }
        if (e.note) extra.push(mdCell(e.note));
        const tail = extra.length ? `（${extra.join(' / ')}）` : '';
        out.push(`- **${f.label}**: ${mdAnswer(rec, schema, f, e)}${tail}`);
      }
      out.push('');
    }

    for (const d of (rec.formDrift || [])) {
      if (out[out.length - 1] !== '' || out.indexOf('## 様式が定義と食い違って見えるところ') < 0) {
        out.push('## 様式が定義と食い違って見えるところ', '',
                 '**実物の様式と、こちらが持っている選択肢の定義が食い違って見えます。**',
                 '読み崩れのこともあるので、自動では直していません。', '');
      }
      out.push(`- **${d.label}**`);
      if ((d.missing || []).length) out.push(`  - 定義にあって読めなかった言葉: ${d.missing.join('、')}`);
      if ((d.extra || []).length) out.push(`  - 実物にあって定義に無い言葉: ${d.extra.join('、')}`);
      if (d.row) out.push(`  - 読めた行: \`${mdCell(d.row)}\``);
    }
    if ((rec.formDrift || []).length) out.push('');

    if ((rec.warnings || []).length) {
      out.push('## 注意', '');
      for (const w of rec.warnings) out.push(`- ${mdCell(w)}`);
      out.push('');
    }
    out.push('## 元ファイル', '');
    for (const p of (rec.pages || [])) {
      out.push(`- ${p.source} の ${p.sourcePage} ページ目 ` +
               `→ 様式の ${p.pageIndex} ページ目（${p.matched ? '判別できた' : '**判別できなかった**'}）`);
    }
    out.push('');
    return out.join('\n');
  }

  function exportMarkdown(records, schema, filename) {
    let body = records.map(r => toMarkdown(r, schema)).join('\n\n---\n\n');
    if (records.length > 1) body = `# 読み取り結果 ${records.length} 件\n\n---\n\n` + body;
    download(filename || `ikensho_${stamp()}.md`, body, 'text/markdown;charset=utf-8');
  }

  global.IkenshoExport = { exportJson, exportCsv, exportFormJson, exportMarkdown,
                           importJson, toRecordJson, toFormJson, toMarkdown,
                           download, flatValue };
})(window);
