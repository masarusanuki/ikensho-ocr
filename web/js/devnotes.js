/**
 * 開発メモ（DEVNOTES.md）の表示。
 * 外部ライブラリを増やさないよう、必要な範囲だけの Markdown 描画を自前で行う。
 */
(function (global) {
  'use strict';
  const esc = s => String(s).replace(/[&<>"]/g,
    c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

  function inline(s) {
    return esc(s)
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
      .replace(/\[([^\]]+)\]\(([^)]+)\)/g, (m, t, u) =>
        /^https?:/.test(u) ? `<a href="${esc(u)}" target="_blank" rel="noopener">${t}</a>` : t);
  }

  function render(md) {
    const out = [];
    const lines = md.split('\n');
    let inCode = false, listType = null, table = null;

    const closeList = () => { if (listType) { out.push(`</${listType}>`); listType = null; } };
    const closeTable = () => {
      if (table) {
        out.push('<table><thead><tr>' +
          table.head.map(h => `<th>${inline(h)}</th>`).join('') + '</tr></thead><tbody>' +
          table.rows.map(r => '<tr>' + r.map(c => `<td>${inline(c)}</td>`).join('') + '</tr>').join('') +
          '</tbody></table>');
        table = null;
      }
    };
    const cells = l => l.replace(/^\||\|$/g, '').split('|').map(s => s.trim());

    for (const raw of lines) {
      const line = raw.replace(/\s+$/, '');
      if (/^```/.test(line)) {
        closeList(); closeTable();
        out.push(inCode ? '</code></pre>' : '<pre><code>');
        inCode = !inCode;
        continue;
      }
      if (inCode) { out.push(esc(raw) + '\n'); continue; }

      if (/^\|.*\|$/.test(line)) {
        closeList();
        if (!table) { table = { head: cells(line), rows: [] }; continue; }
        if (/^\|[\s:\-|]+\|$/.test(line)) continue;
        table.rows.push(cells(line));
        continue;
      }
      closeTable();

      const h = line.match(/^(#{1,4})\s+(.*)$/);
      if (h) { closeList(); out.push(`<h${h[1].length}>${inline(h[2])}</h${h[1].length}>`); continue; }
      if (/^---+$/.test(line)) { closeList(); out.push('<hr>'); continue; }

      const ul = line.match(/^\s*[-*]\s+(.*)$/);
      const ol = line.match(/^\s*\d+\.\s+(.*)$/);
      if (ul || ol) {
        const want = ul ? 'ul' : 'ol';
        if (listType !== want) { closeList(); out.push(`<${want}>`); listType = want; }
        let body = (ul || ol)[1];
        body = body.replace(/^\[( |x|X)\]\s*/, (m, c) =>
          c.trim() ? '☑ ' : '☐ ');
        out.push(`<li>${inline(body)}</li>`);
        continue;
      }
      closeList();
      if (!line.trim()) continue;
      out.push(`<p>${inline(line)}</p>`);
    }
    closeList(); closeTable();
    if (inCode) out.push('</code></pre>');
    return out.join('\n');
  }

  class DevNotes {
    constructor(app) {
      this.app = app;
      this.md = null;
      this.host = document.getElementById('devnotes');
      this.filter = document.getElementById('notes-filter');
      this.toc = document.getElementById('notes-toc');
      this.filter.addEventListener('input', () => this.applyFilter());
      this.toc.addEventListener('change', () => this.jump(this.toc.value));
      document.getElementById('btn-notes-reload').addEventListener('click', () => this.load(true));
    }

    async load(force) {
      if (this.md && !force) return;
      const R = global.IkenshoResolveUrl || (u => u);
      try {
        const res = await fetch(R(`${this.app.pipeline.base}/DEVNOTES.md`));
        if (!res.ok) throw new Error(String(res.status));
        this.md = await res.text();
      } catch (e) {
        this.host.innerHTML =
          '<p class="muted">開発メモ（DEVNOTES.md）を読み込めませんでした。' +
          'リポジトリ直下の DEVNOTES.md を配信対象に含めてください。</p>';
        return;
      }
      this.host.innerHTML = render(this.md);
      this.buildToc();
      this.applyFilter();
    }

    buildToc() {
      const hs = [...this.host.querySelectorAll('h1,h2,h3')];
      hs.forEach((h, i) => { h.id = 'note-' + i; });
      this.toc.innerHTML = '<option value="">目次から移動…</option>' +
        hs.map((h, i) => {
          const pad = h.tagName === 'H3' ? '　　' : (h.tagName === 'H2' ? '　' : '');
          return `<option value="note-${i}">${pad}${esc(h.textContent)}</option>`;
        }).join('');
    }

    jump(id) {
      if (!id) return;
      const el = document.getElementById(id);
      if (el) el.scrollIntoView({ block: 'start', behavior: 'smooth' });
    }

    applyFilter() {
      const q = this.filter.value.trim();
      this.host.querySelectorAll('mark').forEach(m => {
        m.replaceWith(document.createTextNode(m.textContent));
      });
      this.host.normalize();
      if (!q) return;
      const walker = document.createTreeWalker(this.host, NodeFilter.SHOW_TEXT);
      const hits = [];
      let node;
      while ((node = walker.nextNode())) {
        if (node.nodeValue.includes(q)) hits.push(node);
      }
      for (const n of hits) {
        const parts = n.nodeValue.split(q);
        const frag = document.createDocumentFragment();
        parts.forEach((p, i) => {
          if (i) {
            const m = document.createElement('mark');
            m.textContent = q;
            frag.appendChild(m);
          }
          frag.appendChild(document.createTextNode(p));
        });
        n.replaceWith(frag);
      }
      const first = this.host.querySelector('mark');
      if (first) first.scrollIntoView({ block: 'center' });
    }
  }

  global.IkenshoDevNotes = DevNotes;
})(window);
