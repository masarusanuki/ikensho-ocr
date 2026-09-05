# 同梱ライブラリ

オフラインでも動作するよう、以下のライブラリを同梱しています。
いずれも再配布が許可されたライセンスです。本リポジトリ本体のライセンス（MIT）とは別に、
各ライブラリのライセンスが適用されます。

| ファイル | ライブラリ | バージョン | ライセンス |
|---|---|---|---|
| `opencv.js` | [OpenCV.js](https://github.com/TechStark/opencv-js)（@techstark/opencv-js） | 4.10.0-release.1 | Apache-2.0 |
| `pdf.min.mjs` / `pdf.worker.min.mjs` | [pdf.js](https://github.com/mozilla/pdf.js) | 4.6.82 | Apache-2.0 |
| `tesseract.min.js` / `tesseract.worker.min.js` | [tesseract.js](https://github.com/naptha/tesseract.js) | 5.1.1 | Apache-2.0 |
| `tesseract-core-simd.wasm.js` | tesseract.js-core | 5.1.1 | Apache-2.0 |
| `jpn.traineddata.gz` | [tessdata（日本語）](https://github.com/tesseract-ocr/tessdata_best) | 4.0.0 best | Apache-2.0 |

## 取得しなおす

```bash
python3 tools/fetch_vendor.py
```
