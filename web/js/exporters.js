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
    labels.age_computed = '年齢（生年月日から計算）';
    labels.age_written = '年齢（様式の記載）';
    labels.age_matches = '年齢の一致';
    return labels;
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
    const values = {}, meta = {};
    for (const id of schema.order) {
      const e = rec.fields[id];
      if (!e) continue;
      values[id] = e.value === undefined ? null : e.value;
      meta[id] = {
        label: e.label, type: e.type, section: e.section, page: e.page,
        confidence: e.confidence, level: e.level,
        edited: !!e.edited, anonymized: !!e.anonymized,
        raw: e.raw === undefined ? null : e.raw,
        date: e.date || null, era: e.era || '', gregorian: e.gregorian || null,
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
      values,
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
        row.push(flatValue(e), e ? e.confidence : '');
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
          edited: !!m.edited, anonymized: !!m.anonymized, raw: m.raw || '',
          date: m.date || null, era: m.era || '', gregorian: m.gregorian || null,
          kind: f.kind || '',
          label: f.label, type: f.type, section: f.sectionTitle, page: f.page,
          options: f.options,
        };
      }
      out.push({
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

  global.IkenshoExport = { exportJson, exportCsv, importJson, toRecordJson, download, flatValue };
})(window);
