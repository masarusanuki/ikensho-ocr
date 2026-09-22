// seigo2 の生成元 layout.js を実行し、チェック欄と記入欄の座標を取り出す。
// canvas は使わないので、呼ばれるだけの最小限の代用を渡す。
const fs = require('fs');
const src = fs.readFileSync('/home/sanuki/kaigo_nintei/seigo2/src/layout.js', 'utf8');

function fakeCtx() {
  const c = {
    font: '', fillStyle: '', strokeStyle: '', lineWidth: 1,
    textAlign: 'left', textBaseline: 'alphabetic',
    save(){}, restore(){}, beginPath(){}, moveTo(){}, lineTo(){}, stroke(){},
    strokeRect(){}, fillRect(){}, fillText(){}, closePath(){}, arc(){}, fill(){},
    setLineDash(){}, translate(){}, rotate(){}, scale(){}, clip(){}, rect(){},
    // 文字幅は「日本語=フォントサイズ、半角=半分」で近似する
    measureText(s) {
      const m = /(\d+(?:\.\d+)?)px/.exec(c.font || '16px');
      const size = m ? parseFloat(m[1]) : 16;
      let w = 0;
      for (const ch of String(s)) w += (ch.charCodeAt(0) < 0x100 ? size * 0.52 : size);
      return { width: w };
    },
  };
  return c;
}
global.document = { fonts: { add() {} } };
eval(src);
const out = {};
for (const [page, fn] of [[1, 'renderPage1'], [2, 'renderPage2']]) {
  const ctx = fakeCtx();
  const res = LAYOUT[fn](ctx);
  out[page] = {
    W: LAYOUT.W, H: LAYOUT.H,
    boxes: (res.boxes || []).map(b => ({ id: b.id, x: b.x, y: b.y, s: b.s, label: b.label })),
    anchors: (res.anchors || []).map(a => ({ id: a.id, x: a.x, y: a.y, w: a.w,
                                             align: a.align || '', mark: a.mark || '',
                                             big: !!a.big, multiline: a.multiline || 0,
                                             lh: a.lh || 0 })),
  };
}
fs.writeFileSync(process.argv[2], JSON.stringify(out, null, 1));
console.log('page1: 枠', out[1].boxes.length, '記入欄', out[1].anchors.length);
console.log('page2: 枠', out[2].boxes.length, '記入欄', out[2].anchors.length);
