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

  /** Python 側の unicodedata.normalize("NFKC", …) と揃える。 */
  function toHalfWidth(s) {
    const t = String(s == null ? '' : s);
    return (t.normalize ? t.normalize('NFKC') : t).replace(/　/g, ' ');
  }

  function normalize(s) {
    if (!s) return '';
    let t = toHalfWidth(normalizeVariants(s));
    t = t.replace(/ヶ/g, 'ケ').replace(/ヵ/g, 'カ');
    t = t.replace(/[\s・･,、。.\-‐－―—ー_/\\()（）\[\]「」【】:：;；'"]+/g, '');
    return t.toLowerCase();
  }

  function bigrams(s) {
    const set = new Set();
    if (s.length < 2) { if (s) set.add(s); return set; }
    for (let i = 0; i < s.length - 1; i++) set.add(s.slice(i, i + 2));
    return set;
  }

  /** 編集距離。OCR の誤りは1文字置換が多いため、この指標がよく効く。 */
  function levenshtein(a, b) {
    if (a === b) return 0;
    if (!a.length) return b.length;
    if (!b.length) return a.length;
    let prev = new Array(b.length + 1);
    for (let j = 0; j <= b.length; j++) prev[j] = j;
    for (let i = 1; i <= a.length; i++) {
      const cur = [i];
      for (let j = 1; j <= b.length; j++) {
        cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1,
                          prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
      }
      prev = cur;
    }
    return prev[b.length];
  }

  /**
   * 辞書語が読み取り結果のどこかに現れているとみなして照合する。
   * OCR 結果には「（保存期）」のような余分な文字が付くことが多いので、
   * 全体一致ではなく、辞書語と同じ長さの窓を滑らせて最も近い位置で評価する。
   */
  function partialSimilarity(query, term) {
    if (!query || !term) return 0;
    if (term.length > query.length) {
      // 辞書語の方が長い＝読み取れた内容は辞書語の一部でしかない。
      // 窓をずらして一致させると「骨折」が「圧迫骨折」に化けるので、
      // 全体の編集距離で「足りない文字がどれだけあるか」を評価する。
      return Math.max(0, 1 - levenshtein(query, term) / term.length);
    }
    const m = term.length;
    if (!m) return 0;
    let best = 0;
    for (let start = 0; start + m <= query.length; start++) {
      for (const width of new Set([m, Math.min(m + 2, query.length - start)])) {
        const win = query.substr(start, width);
        const d = levenshtein(win, term);
        best = Math.max(best, 1 - d / Math.max(win.length, m));
        if (best >= 1) return 1;
      }
    }
    return Math.max(0, best);
  }

  /**
   * OCR 結果と辞書語の類似度 0..1。
   * 2-gram の Dice 係数と、編集距離による部分一致の大きい方を採る。
   * Dice だけでは「骨粗葵症」と「骨粗鬆症」のような1文字違いを取り逃す。
   */
  function similarity(a, b) {
    const na = normalize(a), nb = normalize(b);
    if (!na || !nb) return 0;
    if (na === nb) return 1;
    const ga = bigrams(na), gb = bigrams(nb);
    let inter = 0;
    for (const g of ga) if (gb.has(g)) inter++;
    let dice = (ga.size + gb.size) ? (2 * inter) / (ga.size + gb.size) : 0;
    // 辞書語が読み取り結果に含まれている場合だけ加点する。逆は加点しない。
    if (na.includes(nb)) dice = Math.max(dice, 0.55 + 0.35 * nb.length / Math.max(na.length, 1));
    return Math.max(dice, partialSimilarity(na, nb));
  }

  // OCR がよく取り違える字の訂正。前後の文字種を見て「こちらしかあり得ない」場合だけ直す。
  const HIRA = 'ぁ-ゟ', KATA = 'ァ-ヿ', KANJI = '㐀-鿿豈-﫿';
  const JP = HIRA + KATA + KANJI;
  const CONTEXT_FIXES = [
    ['カタカナのカを漢字の力と誤認', new RegExp(`(?<=[${KATA}])力(?=[${KATA}])`, 'g'), 'カ'],
    ['カタカナのロを漢字の口と誤認', new RegExp(`(?<=[${KATA}])口(?=[${KATA}])`, 'g'), 'ロ'],
    ['カタカナのニを漢字の二と誤認', new RegExp(`(?<=[${KATA}])二(?=[${KATA}])`, 'g'), 'ニ'],
    ['カタカナのヘをひらがなのへと誤認', new RegExp(`(?<=[${KATA}])へ(?=[${KATA}])`, 'g'), 'ヘ'],
    ['ひらがなのへをカタカナのヘと誤認', new RegExp(`(?<=[${HIRA}])ヘ(?=[${HIRA}])`, 'g'), 'へ'],
    ['長音記号を漢数字の一と誤認', new RegExp(`(?<=[${KATA}])一(?=[${KATA}])`, 'g'), 'ー'],
    ['長音記号をハイフンと誤認', new RegExp(`(?<=[${KATA}])[-−–—](?=[${KATA}])`, 'g'), 'ー'],
  ];

  // 医療・介護文書でよくある誤字
  const WORD_FIXES = {
    '遍数回':'週数回','遍1回':'週1回','遍2回':'週2回','遍3回':'週3回',
    '山床':'臥床','卧床':'臥床','褥創':'褥瘡','褥瘖':'褥瘡','嚥化':'嚥下','臙下':'嚥下',
    '肺災':'肺炎','認知庄':'認知症','麻庫':'麻痺','麻痴':'麻痺','徘個':'徘徊','俳徊':'徘徊',
    '介謹':'介護','介穫':'介護','訪間':'訪問','訪聞':'訪問','白立':'自立','リハピリ':'リハビリ',
    '高血庄':'高血圧','血庄':'血圧','骨析':'骨折','内脹':'内服','脹薬':'服薬','排洩':'排泄',
    '更依':'更衣','人浴':'入浴','転倒':'転倒','頼倒':'転倒','安走':'安定','経渦':'経過',
    '痘状':'症状','治僚':'治療','糠尿病':'糖尿病','見寺り':'見守り','リハビリテーシヨン':'リハビリテーション',
  };
  const NOISE = '|｜!！"\'`^~*#$%&@={}<>\\';

  /**
   * 日本語として妥当か調べ、誤字を直す。
   * OCR が失敗した欄は記号やアルファベットの羅列になるので、
   * 「日本語度」が下がり、確認画面で要確認として扱える。
   */
  function proofread(text) {
    if (!text || !text.trim()) return { text: text || '', corrections: [], score: 1 };
    const corrections = [];
    let out = '';
    for (const ch of text) {
      if (NOISE.includes(ch)) { corrections.push([ch, '']); continue; }
      out += ch;
    }
    out = out.replace(/[ 　]{2,}/g, ' ').replace(/^[\s.,、。・:：;；\-ー_]+/, '').trim();
    for (const [reason, re, rep] of CONTEXT_FIXES) {
      out = out.replace(re, m => { corrections.push([m, rep]); return rep; });
    }
    for (const [wrong, right] of Object.entries(WORD_FIXES)) {
      if (out.includes(wrong)) { out = out.split(wrong).join(right); corrections.push([wrong, right]); }
    }
    return { text: out, corrections, score: japaneseScore(out) };
  }

  const VALID_RE = new RegExp(`[${JP}0-9０-９a-zA-Zａ-ｚＡ-Ｚ\\s、。・（）()「」『』〔〕：:；;／/＋+－\\-.,％%℃ー～〜]`);

  /** 日本語として成立している度合い 0..1。 */
  function japaneseScore(text) {
    const t = (text || '').trim();
    if (!t) return 1;
    const chars = Array.from(t);
    const valid = chars.filter(c => VALID_RE.test(c)).length / chars.length;
    const digits = chars.filter(c => /[0-9０-９]/.test(c)).length;
    if (digits >= chars.length * 0.6) return valid;
    const jp = chars.filter(c => new RegExp(`[${JP}]`).test(c)).length / chars.length;
    return Math.min(1, valid * 0.6 + Math.min(jp * 2, 1) * 0.4);
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
    stripBoilerplate(text, threshold = 0.80) {
      const lex = this.lexicons.boilerplate;
      if (!lex || !text) return text;
      // 「定型文のどこかに含まれていれば捨てる」では『認知症』『骨折』のような
      // 正しい記入内容まで消えてしまう。長さの近さも条件に入れる。
      const entries = lex.entries.map(e => [e, normalize(e.name)]);
      const kept = [];
      for (const line of String(text).split('\n')) {
        const n = normalize(line);
        if (!n) continue;
        let drop = false;
        for (const [e, en] of entries) {
          if (!en) continue;
          const ratio = Math.min(n.length, en.length) / Math.max(n.length, en.length);
          if (ratio < 0.70) continue;
          if (n === en || similarity(line, e.name) >= threshold) { drop = true; break; }
        }
        if (!drop) kept.push(line);
      }
      return kept.join('\n').trim();
    }

    /** OCR結果を辞書で補正し {value, confidence, candidates} を返す。 */
    correct(fieldId, text, baseConfidence) {
      let t = this.stripBoilerplate(cleanOcr(text));
      const pr = proofread(t);
      const corrections = pr.corrections;
      t = pr.text;
      const jscore = pr.score;
      const key = this.fieldMap[fieldId];
      const extra = { corrections, japaneseScore: jscore };
      if (jscore < 0.6) baseConfidence *= 0.6;
      if (!key || !this.lexicons[key] || !t) {
        return Object.assign({ value: t, confidence: baseConfidence, candidates: [] }, extra);
      }
      const hits = this.search(key, t);
      const candidates = hits.map(h => ({
        value: h.entry.name, score: +h.score.toFixed(4),
        icd10: h.entry.icd10 || '', tokutei: !!h.entry.tokutei
      }));
      if (!hits.length) return { value: t, confidence: baseConfidence * 0.7, candidates: [] };
      const best = hits[0];
      if (normalize(best.entry.name) === normalize(t)) {
        return Object.assign({ value: best.entry.name, confidence: Math.min(1, baseConfidence + 0.2), candidates }, extra);
      }
      if (best.score >= AUTO_ADOPT) {
        return Object.assign({ value: best.entry.name,
                 confidence: Math.min(0.95, baseConfidence * 0.5 + best.score * 0.5), candidates }, extra);
      }
      return Object.assign({ value: t, confidence: baseConfidence * 0.75, candidates }, extra);
    }
  }

  global.IkenshoDicts = { Dictionaries, similarity, normalize, cleanOcr,
                          normalizeVariants, levenshtein, proofread, japaneseScore };
})(window);
