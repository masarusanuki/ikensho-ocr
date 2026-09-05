/**
 * 医療辞書によるOCR補正と入力補完（ブラウザ版）。
 * Python 版 ikensho_ocr/dictionaries.py と同じ判定ロジックを持つ。
 */
(function (global) {
  'use strict';

  const AUTO_ADOPT = 0.72;
  const SUGGEST_MIN = 0.34;
  const MAX_CANDIDATES = 8;

  // 簡体字・異体字 -> 日本語常用字体（OCR が中国語系モデルの場合の補正）
  const VARIANT_MAP = {
    '变':'変','两':'両','调':'調','顷':'頃','关':'関','实':'実','发':'発','应':'応',
    '图':'図','归':'帰','气':'気','乐':'楽','检':'検','验':'験','总':'総','续':'続',
    '经':'経','给':'給','级':'級','缩':'縮','练':'練','职':'職','认':'認','护':'護',
    '议':'議','访':'訪','诊':'診','语':'語','读':'読','说':'説','谈':'談','课':'課',
    '讲':'講','谢':'謝','识':'識','劳':'労','效':'効','单':'単','严':'厳','带':'帯',
    '剂':'剤','济':'済','准':'準','铁':'鉄','银':'銀','录':'録','险':'険','陷':'陥',
    '隐':'隠','难':'難','头':'頭','颜':'顔','愿':'願','类':'類','饮':'飲','龄':'齢',
    '齿':'歯','药':'薬','养':'養','营':'営','术':'術','创':'創','伤':'傷','疗':'療',
    '综':'総','态':'態','脏':'臓','肾':'腎','脑':'脳','脉':'脈','动':'動','运':'運',
    '转':'転','达':'達','远':'遠','适':'適','选':'選','进':'進','过':'過','边':'辺',
    '连':'連','压':'圧','现':'現','视':'視','观':'観','规':'規','觉':'覚','书':'書',
    '东':'東','车':'車','长':'長','门':'門','问':'問','闻':'聞','间':'間','闭':'閉',
    '开':'開','对':'対','产':'産','亚':'亜','价':'価','优':'優','县':'県','岁':'歳',
    '师':'師','帐':'帳','团':'団','园':'園','围':'囲','场':'場','坏':'壊','块':'塊',
    '处':'処','备':'備','复':'復','夹':'挟','夺':'奪','妇':'婦','学':'学','宁':'寧',
    '宝':'宝','审':'審','宫':'宮','宽':'寛','导':'導','将':'将','层':'層','岛':'島',
  };

  function normalizeVariants(s) {
    if (!s) return '';
    let out = '';
    for (const ch of s) out += (VARIANT_MAP[ch] || ch);
    return out;
  }

  function toHalfWidth(s) {
    return s.replace(/[！-～]/g, c => String.fromCharCode(c.charCodeAt(0) - 0xFEE0))
            .replace(/　/g, ' ');
  }

  function normalize(s) {
    if (!s) return '';
    let t = toHalfWidth(normalizeVariants(s));
    t = t.replace(/ヶ/g, 'ケ').replace(/ヵ/g, 'カ');
    t = t.replace(/[\s・･,、。.\-‐－―—_/\\()（）\[\]「」【】:：;；'"]+/g, '');
    return t.toLowerCase();
  }

  function bigrams(s) {
    const set = new Set();
    if (s.length < 2) { if (s) set.add(s); return set; }
    for (let i = 0; i < s.length - 1; i++) set.add(s.slice(i, i + 2));
    return set;
  }

  function similarity(a, b) {
    const na = normalize(a), nb = normalize(b);
    if (!na || !nb) return 0;
    if (na === nb) return 1;
    const ga = bigrams(na), gb = bigrams(nb);
    let inter = 0;
    for (const g of ga) if (gb.has(g)) inter++;
    let dice = (ga.size + gb.size) ? (2 * inter) / (ga.size + gb.size) : 0;
    if (na.includes(nb) || nb.includes(na)) {
      dice = Math.max(dice, 0.55 + 0.35 * Math.min(na.length, nb.length) / Math.max(na.length, nb.length));
    }
    return dice;
  }

  /** 罫線や括弧だけの読み取りは無意味なので落とす。 */
  function cleanOcr(text) {
    if (!text) return '';
    const t = normalizeVariants(text).trim();
    if (t && [...t].every(ch => '()（）［］[]{}｛｝|｜/\\_—―‐-・.,、。 　:：;；'.includes(ch))) return '';
    return t;
  }

  class Dictionaries {
    constructor() { this.lexicons = {}; this.fieldMap = {}; }

    async load(baseUrl) {
      const R = global.IkenshoResolveUrl || (u => u);
      const names = ['departments', 'diseases', 'body_sites', 'infections',
                     'clinic_suffix', 'prefectures', 'boilerplate'];
      this.fieldMap = await fetch(R(`${baseUrl}/field_map.json`)).then(r => r.json());
      await Promise.all(names.map(async n => {
        try {
          const raw = await fetch(R(`${baseUrl}/${n}.json`)).then(r => r.json());
          this.lexicons[n] = { key: n, label: raw.label || n, entries: raw.entries || [] };
        } catch (e) { /* 任意の辞書は無くてもよい */ }
      }));
      return this;
    }

    search(key, query, limit = MAX_CANDIDATES, minScore = SUGGEST_MIN) {
      const lex = this.lexicons[key];
      if (!lex || !query) return [];
      const scored = [];
      for (const e of lex.entries) {
        const s = similarity(query, e.name);
        if (s >= minScore) scored.push({ entry: e, score: s });
      }
      scored.sort((a, b) => (b.score - a.score) ||
                            ((a.entry.tokutei ? 0 : 1) - (b.entry.tokutei ? 0 : 1)) ||
                            (a.entry.name.length - b.entry.name.length));
      return scored.slice(0, limit);
    }

    /** 入力補完（前方一致優先、部分一致で補う）。 */
    suggest(fieldId, query, limit = 12) {
      const key = this.fieldMap[fieldId];
      const lex = this.lexicons[key];
      if (!lex) return [];
      const q = normalize(query || '');
      if (!q) return lex.entries.slice(0, limit);
      const starts = [], contains = [];
      for (const e of lex.entries) {
        const n = normalize(e.name);
        if (n.startsWith(q)) starts.push(e);
        else if (n.includes(q)) contains.push(e);
      }
      if (starts.length + contains.length < limit) {
        for (const { entry } of this.search(key, query, limit, 0.45)) {
          if (!starts.includes(entry) && !contains.includes(entry)) contains.push(entry);
        }
      }
      return starts.concat(contains).slice(0, limit);
    }

    /** 様式に印刷されている文言を読み取り結果から取り除く。 */
    stripBoilerplate(text, threshold = 0.62) {
      const lex = this.lexicons.boilerplate;
      if (!lex || !text) return text;
      const kept = [];
      for (const line of String(text).split('\n')) {
        const n = normalize(line);
        if (!n) continue;
        if (n.length < 4) {
          if (lex.entries.some(e => normalize(e.name).includes(n))) continue;
          kept.push(line); continue;
        }
        const hit = lex.entries.some(e => similarity(line, e.name) >= threshold);
        if (!hit) kept.push(line);
      }
      return kept.join('\n').trim();
    }

    /** OCR結果を辞書で補正し {value, confidence, candidates} を返す。 */
    correct(fieldId, text, baseConfidence) {
      let t = this.stripBoilerplate(cleanOcr(text));
      const key = this.fieldMap[fieldId];
      if (!key || !this.lexicons[key] || !t) {
        return { value: t, confidence: baseConfidence, candidates: [] };
      }
      const hits = this.search(key, t);
      const candidates = hits.map(h => ({
        value: h.entry.name, score: +h.score.toFixed(4),
        icd10: h.entry.icd10 || '', tokutei: !!h.entry.tokutei
      }));
      if (!hits.length) return { value: t, confidence: baseConfidence * 0.7, candidates: [] };
      const best = hits[0];
      if (best.score >= 0.999) {
        return { value: best.entry.name, confidence: Math.min(1, baseConfidence + 0.2), candidates };
      }
      if (best.score >= AUTO_ADOPT) {
        return { value: best.entry.name,
                 confidence: Math.min(0.95, baseConfidence * 0.5 + best.score * 0.5), candidates };
      }
      return { value: t, confidence: baseConfidence * 0.75, candidates };
    }
  }

  global.IkenshoDicts = { Dictionaries, similarity, normalize, cleanOcr, normalizeVariants };
})(window);
