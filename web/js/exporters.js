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
        edited: !!e.edited, raw: e.raw === undefined ? null : e.raw,
      };
    }
    return {
      schema_version: schema.version,
      form_name: schema.formName,
      template_id: rec.templateId,
      ocr_engine: rec.ocrEngine || 'none',
      read_at: rec.readAt,
      sources: rec.pages.map(p => ({
        source: p.source, source_page: p.sourcePage,
        page_index: p.pageIndex, matched: p.matched,
        score: p.score, dewarped: p.dewarped,
      })),
      warnings: rec.warnings || [],
      values, meta,
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
    const head = ['record_no', 'template_id', 'read_at', 'sources', 'warnings'];
    for (const id of schema.order) {
      const f = schema.byId[id];
      head.push(`${id}`, `${id}__confidence`);
    }
    const labelRow = ['#', '様式', '読取日時', '元ファイル', '警告'];
    for (const id of schema.order) {
      labelRow.push(schema.byId[id].label, '確信度');
    }
    const lines = [head.map(csvEscape).join(','), labelRow.map(csvEscape).join(',')];
    records.forEach((rec, i) => {
      const row = [
        i + 1, rec.templateId || '', rec.readAt || '',
        [...new Set(rec.pages.map(p => p.source))].join('；'),
        (rec.warnings || []).join('；'),
      ];
      for (const id of schema.order) {
        const e = rec.fields[id];
        row.push(flatValue(e), e ? e.confidence : '');
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
          edited: !!m.edited, raw: m.raw || '',
          label: f.label, type: f.type, section: f.sectionTitle, page: f.page,
          options: f.options,
        };
      }
      out.push({
        fields, templateId: r.template_id, ocrEngine: r.ocr_engine,
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
