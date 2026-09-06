# 作業ログ

このアプリを作る間に、**何を頼まれ、どこを、どれだけ書き換えたか**の記録です。

- 下半分（「全体」以降）は `git` の履歴から自動で作っています。手で書き換えないでください。
- 更新の仕方:

```bash
python tools/build_worklog.py          # コミットのあとに実行する
python tools/build_worklog.py --check  # 最新かどうかだけ調べる（終了コード1なら要更新）
```

「コミット番号」は下の[コミット一覧](#コミット一覧)の番号です。

---

## 指示と対応の対照表

状態は ✅=対応済 / △=一部 / ❌=未対応。

### 未対応・一部のみ

| 指示 | 状態 | 現状 |
|---|---|---|
| 「該当箇所」（拡大プレビュー）を横スクロール可能に | ❌ | 着手直後 |
| 医療機関リストを厚労省から都道府県ごとに | △ | 関東信越10都県 36,451件のみ。他7厚生局は一覧ページが404（20） |
| 医療機関リストを最新版にできるボタン | ❌ | 取得スクリプト `tools/fetch_hospitals.py` のみ。管理画面のボタンは未 |
| 医療機関名をLLMで気を効かせる | △ | 一覧からの選択は実装（20）。LLMでの補正は未 |
| ローカルで動く1つのファイル | △ | 単一HTMLは作成済（3）。ただし `file://` ではブラウザの制約でtesseract.jsが起動できず、チェック欄の読み取りのみ |
| Python版の医療機関名を一覧で補正 | ❌ | ブラウザ版のみ（20） |

### 読み取りと入力

| 指示 | 状態 | コミット |
|---|---|---|
| 2ページのPDF・画像を1つでも複数でもアップロード | ✅ | 3 |
| スマホ・タブレットのカメラ（1ページ1ファイル）に対応 | ✅ | 3 |
| OCRで読み取る | ✅ | 2, 9 |
| LLMを極力使わない | ✅ | 2（チェック欄はOCR不要。LLMは記述欄と補正のみ） |
| masterから項目を確認して定義する | ✅ | 1 |
| JSON・CSVで保存 | ✅ | 2 |
| 出力されるJSON・CSVの説明を開発メモに | ✅ | 12 |
| 読み取る場所が違う→masterでサンプルを作り自己学習 | ✅ | 8, 10 |
| 枠の場所は決まっているので位置情報はそれを基準に | ✅ | 1, 10 |
| OCRのあと日本語as チェックと誤字訂正 | ✅ | 11 |
| 記述部分のテキストはLLMで読ませる | ✅ | 15 |
| LLMは自動で全て適用する | ✅ | 18 |
| ふりがながカタカナならひらがなに直し、メッセージを出す | ✅ | 18 |
| テンプレートの置き場所を指定できるように | ✅ | 15 |

### 数字だけの欄の精度

| 指示 | 状態 | コミット |
|---|---|---|
| 元号は決まっているので数字だけを読む | ✅ | 13, 14 |
| 西暦に直した値も別に保存（機械学習のため） | ✅ | 14 |
| 記入日 | ✅ | 13, 15 |
| 生年月日（月は1〜12） | ✅ | 14, 15 |
| 最終診察日 | ✅ | 15 |
| 発症年月日 | ✅ | 15 |
| 性別は2択なのでどちらかを当てる | ✅ | 14 |
| 電話番号は市外局番の括弧をつけず、ハイフンは残す | ✅ | 16 |

### 辞書とLLM

| 指示 | 状態 | コミット |
|---|---|---|
| 医療用語なので辞書を入れる | ✅ | 2 |
| 診療科しか入らない欄には診療科の辞書 | ✅ | 2 |
| 病名はICDも入れる | ✅ | 2 |
| できる限り選択＆文字補完 | ✅ | 3 |
| 病名を一覧から探すロジック | ✅ | 15 |
| CPUでも動くLLM（遅くならない程度） | ✅ | 11 |
| LLMを既定で動かす | ✅ | 12 |
| thinkingのないQwenに変更 | ✅ | 11 |
| モデルごとのベンチマークを開発ページに | ✅ | 13 |
| モデルを選べるダウンロードボタン | ✅ | 13 |

### 確認・編集画面

| 指示 | 状態 | コミット |
|---|---|---|
| 文字やチェックの確からしさを色で見分けられるように | ✅ | 3 |
| 確からしさをタグだけでなく背景にも | ✅ | 15 |
| 左の画像にも項目ごとの判定色 | ✅ | 18 |
| 右の一覧は様式の表示順に並べる | ✅ | 10 |
| 左の画像をクリックすると右の該当項目へ移動 | ✅ | 10 |
| 左の画像の下部が見えない→左右を別々にスクロール | ✅ | 10 |
| 修正を確定したことが分かるように | ✅ | 17 |
| 確定は緑ではなく黄緑で区別 | ✅ | 17 |
| 「削除して確定」ボタン | ✅ | 18 |
| OCR生読みも候補ボタンに追加 | ✅ | 17 |
| 拡大表示が横スクロールできない | ✅ | 19 |
| 音声入力（記述部分だけ） | ✅ | 19 |
| 「読み取り xx / 107 項目」を上に固定表示 | ✅ | 19 |
| 病院名を確定すると住所も確定 | ✅ | 20 |
| 関連する項目を1つにまとめて表示 | ✅ | 20 |

### masterの解釈の直し

| 指示 | 状態 | コミット |
|---|---|---|
| 「(2) 不安定の場合の具体的な状況」と安定性の順序が逆 | ✅ | 15 |
| 2ページ目 4) その他は行ごとに項目を作る | ✅ | 15 |
| 「(6) サービス提供時の留意事項」はチェック＋詳細 | ✅ | 15 |
| 「(2) 栄養・食生活上の留意点」は2項目（チェックとテキスト） | ✅ | 19 |
| 「(5) 医学的管理の必要性」はレイアウトもmasterと同じに | ✅ | 18 |
| 「(3) BPSDの有無」と「(3) BPSD症状」を1つにまとめる | ✅ | 20 |

### 匿名化と運用

| 指示 | 状態 | コミット |
|---|---|---|
| 研究用で白抜きの氏名は「匿名化済み」と入れる | ✅ | 7 |
| 「匿名化加工済みデータ」ボタンで住所などを「マスク済み」に | ✅ | 7 |
| サイトに takahashi でパスワード | ✅ | 12 |
| システムの管理画面 | ✅ | 3 |
| 品質チェックのagentを入れてダブルチェック | ✅ | 17 |

### 配布と説明書

| 指示 | 状態 | コミット |
|---|---|---|
| インストールなども簡単に | ✅ | 9 |
| web版 | ✅ | 3 |
| GitHubに開発状況を上げる | ✅ | 1〜20 |
| tesseractを入れさせない／OS別の手順（Rocky・Ubuntu・Mac・Windows） | ✅ | 9 |
| Windows以外はPythonベース | ✅ | 9 |
| WindowsはDocker | ✅ | 12 |
| 技術者用のページをコマンド含めて細かく | ✅ | 12 |
| 開発メモは画面内切り替えでなくページを分けてメニュー | ✅ | 12 |
| 開発メモは `/home/sanuki/kaigo_nintei`、公開分だけ `/var/www/html/test-deploy/kaigo_nintei/` | ✅ | 12 |
| copyright を Masaru Sanuki, University of Tsukuba & Department of Biomedical Informatics, University of Tsukuba Hospital に | ✅ | 3 |
| サンプルファイルにもアクセスできるように | ✅ | 12 |
| サンプルはプレビューと個別ダウンロード、まとめてダウンロードも | ✅ | 12 |
| サンプルに「検証」ボタン（押すと読み取りが始まる） | ✅ | 15 |
| 作業ログを残し、どの程度編集したか分かるように | ✅ | このファイル |

---

<!-- AUTO_START -->

## 全体

- 期間: 2026-09-06 07:03 〜 2026-09-06 15:14
- コミット 28 件 / 追加 30,072 行 / 削除 4,808 行

### 今のコード量（コメント・空行を含む行数）

| 置き場所 | ファイル | 行 |
|---|---:|---:|
| ブラウザ版（確認・編集画面） | 18 | 5,673 |
| Python版（読み取り本体） | 22 | 3,964 |
| 生成・検証スクリプト | 22 | 3,734 |
| 配布（Docker・インストーラ） | 1 | 33 |
| **合計** | **63** | **13,404** |

### どこを何行いじったか（累計）

| 置き場所 | 追加 | 削除 | 触ったファイル |
|---|---:|---:|---:|
| 様式テンプレート | 6,694 | 769 | 11 |
| ブラウザ版（確認・編集画面） | 6,127 | 408 | 23 |
| その他（README・設定など） | 4,821 | 3,002 | 21 |
| Python版（読み取り本体） | 4,323 | 352 | 23 |
| 生成・検証スクリプト | 3,874 | 162 | 22 |
| 辞書 | 1,773 | 0 | 9 |
| 項目定義 | 1,227 | 82 | 1 |
| 説明書 | 801 | 27 | 12 |
| 配布（Docker・インストーラ） | 345 | 6 | 7 |
| CI | 87 | 0 | 2 |

## コミット一覧

| # | 日時 | 内容 | ファイル | 追加 | 削除 |
|---:|---|---|---:|---:|---:|
| 1 | 2026-09-06 07:03 | 様式定義とテンプレート生成基盤を追加 | 14 | 6,928 | 0 |
| 2 | 2026-09-06 07:14 | 読み取りエンジンと医療辞書を追加 | 24 | 3,150 | 29 |
| 3 | 2026-09-06 07:47 | ブラウザ版・Python版・管理画面・医療辞書を追加 | 62 | 7,487 | 104 |
| 4 | 2026-09-06 07:47 | ビルド成果物をリポジトリから除外し、スクリーンショットを軽量化 | 27 | 5 | 2,932 |
| 5 | 2026-09-06 07:48 | 検証結果を記載し、記入済み様式が写るスクリーンショットを公開対象から外す | 8 | 25 | 2 |
| 6 | 2026-09-06 07:49 | 同梱ライブラリのライセンス表記と取得スクリプトを追加 | 2 | 58 | 0 |
| 7 | 2026-09-06 07:54 | 匿名化加工済みデータ（研究用）に対応 | 21 | 441 | 89 |
| 8 | 2026-09-06 08:00 | 様式間のテキスト欄転写を、行ごとの局所写像に置き換え | 7 | 385 | 343 |
| 9 | 2026-09-06 08:33 | OCR精度の改善と、OS別の配布手段を整備 | 27 | 1,477 | 72 |
| 10 | 2026-09-06 09:14 | テキスト欄の読み取り位置を修正し、確認画面を改善 | 13 | 1,792 | 335 |
| 11 | 2026-09-06 09:24 | 思考モードなしのQwenに変更し、OCR後の日本語チェックを追加 | 6 | 174 | 17 |
| 12 | 2026-09-06 10:32 | LLMを既定で有効化し、Docker配布とドキュメントページを整備 | 20 | 1,326 | 220 |
| 13 | 2026-09-06 10:49 | 日付欄を数字入力にし、LLMモデルの選択・ダウンロードとモデル比較を追加 | 23 | 1,003 | 12 |
| 14 | 2026-09-06 11:04 | 日付欄は数字だけを読み、西暦に直した値を別に保存する | 12 | 293 | 38 |
| 15 | 2026-09-06 11:32 | 日付欄を様式に依存せず読み、確認画面と検証手段を整備 | 24 | 1,209 | 47 |
| 16 | 2026-09-06 11:34 | 電話番号と郵便番号の書式を整える | 2 | 37 | 2 |
| 17 | 2026-09-06 11:56 | レビューで見つかった重大な不具合を修正し、確定の状態を追加 | 16 | 356 | 114 |
| 18 | 2026-09-06 12:11 | 確認画面を原本に近づけ、確定・削除の操作を追加 | 5 | 206 | 20 |
| 19 | 2026-09-06 12:16 | 拡大表示の横スクロール、音声入力、栄養留意点の位置修正 | 7 | 203 | 10 |
| 20 | 2026-09-06 12:31 | 関連する項目をまとめて表示し、医療機関名を一覧から選べるようにした | 6 | 498 | 126 |
| 21 | 2026-09-06 13:59 | 操作ログと利用者トークンを追加し、作業ログを残すようにした | 12 | 1,398 | 12 |
| 22 | 2026-09-06 13:59 | 作業ログを最新のコミットに合わせた | 1 | 5 | 5 |
| 23 | 2026-09-06 14:19 | 記述欄の左端を広げ、読めた文字数を書き込み量と突き合わせる | 9 | 552 | 21 |
| 24 | 2026-09-06 14:19 | 作業ログを更新 | 1 | 31 | 9 |
| 25 | 2026-09-06 14:24 | 該当箇所の拡大表示を掴んで横に動かせるようにした | 3 | 64 | 4 |
| 26 | 2026-09-06 14:24 | 作業ログを更新 | 1 | 22 | 6 |
| 27 | 2026-09-06 14:53 | 2回目のレビューで見つかった不具合を修正 | 14 | 579 | 233 |
| 28 | 2026-09-06 15:14 | 医療機関名を一覧と突き合わせ、記述の1文字は空にする | 6 | 368 | 6 |

## コミットごとの中身

### 1. 様式定義とテンプレート生成基盤を追加

`39db891` 2026-09-06 07:03 — 14 ファイル ／ +6,928 −0

- `templates/sample_v1.json` +2533 −0
- `templates/official_v1.json` +2480 −0
- `schema/ikensho.schema.json` +984 −0
- `tools/form_definition.py` +338 −0
- `tools/build_consensus_template.py` +300 −0
- `tools/build_master_template.py` +198 −0
- `tools/preview_template.py` +27 −0
- `tools/preview_on_ref.py` +26 −0
- `.gitignore` +21 −0
- `LICENSE` +21 −0
- `templates/refs/official_v1_p1.png` +0 −0
- `templates/refs/official_v1_p2.png` +0 −0
- `templates/refs/sample_v1_p1.png` +0 −0
- `templates/refs/sample_v1_p2.png` +0 −0

### 2. 読み取りエンジンと医療辞書を追加

`95ae3ca` 2026-09-06 07:14 — 24 ファイル ／ +3,150 −29

- `dict/diseases.json` +910 −0
- `dict/boilerplate.json` +254 −0
- `tools/build_dictionaries.py` +216 −0
- `python/ikensho_ocr/extract.py` +208 −0
- `python/ikensho_ocr/dictionaries.py` +193 −0
- `python/ikensho_ocr/ocr.py` +182 −0
- `dict/departments.json` +149 −0
- `dict/prefectures.json` +146 −0
- `dict/body_sites.json` +137 −0
- `python/ikensho_ocr/imaging.py` +127 −0
- `python/ikensho_ocr/checkbox.py` +122 −0
- `python/ikensho_ocr/align.py` +104 −0
- `python/ikensho_ocr/kanji_norm.py` +87 −0
- `python/ikensho_ocr/templates.py` +63 −0
- `python/ikensho_ocr/schema.py` +62 −0
- ほか 9 ファイル +190 −29

### 3. ブラウザ版・Python版・管理画面・医療辞書を追加

`2a071cf` 2026-09-06 07:47 — 62 ファイル ／ +7,487 −104

- `dist/web/js/pipeline.js` +425 −0
- `web/js/pipeline.js` +425 −0
- `dist/web/js/review.js` +375 −0
- `web/js/review.js` +375 −0
- `dist/web/js/engine.js` +369 −0
- `web/js/engine.js` +369 −0
- `dist/web/js/admin.js` +329 −0
- `web/js/admin.js` +329 −0
- `dist/web/js/app.js` +318 −0
- `web/js/app.js` +318 −0
- `dist/web/vendor/tesseract-core-simd.wasm.js` +281 −0
- `web/vendor/tesseract-core-simd.wasm.js` +281 −0
- `DEVNOTES.md` +249 −0
- `dist/web/index.html` +236 −0
- `web/index.html` +236 −0
- ほか 47 ファイル +2572 −104

### 4. ビルド成果物をリポジトリから除外し、スクリーンショットを軽量化

`851801c` 2026-09-06 07:47 — 27 ファイル ／ +5 −2,932

- `dist/web/js/pipeline.js` +0 −425
- `dist/web/js/review.js` +0 −375
- `dist/web/js/engine.js` +0 −369
- `dist/web/js/admin.js` +0 −329
- `dist/web/js/app.js` +0 −318
- `dist/web/vendor/tesseract-core-simd.wasm.js` +0 −281
- `dist/web/index.html` +0 −236
- `dist/web/style.css` +0 −193
- `dist/web/js/dicts.js` +0 −177
- `dist/web/js/exporters.js` +0 −132
- `dist/web/vendor/opencv.js` +0 −48
- `dist/web/vendor/pdf.min.mjs` +0 −21
- `dist/web/vendor/pdf.worker.min.mjs` +0 −21
- `.gitignore` +5 −1
- `dist/web/vendor/tesseract.min.js` +0 −3
- ほか 12 ファイル +0 −3

### 5. 検証結果を記載し、記入済み様式が写るスクリーンショットを公開対象から外す

`a06f1a4` 2026-09-06 07:48 — 8 ファイル ／ +25 −2

- `README.md` +13 −0
- `DEVNOTES.md` +10 −0
- `.gitignore` +2 −2
- `docs/screenshots/01_upload.jpg` +0 −0
- `docs/screenshots/02_review.jpg` +0 −0
- `docs/screenshots/03_field_focus.jpg` +0 −0
- `docs/screenshots/04_records.jpg` +0 −0
- `docs/screenshots/05_admin.jpg` +0 −0

### 6. 同梱ライブラリのライセンス表記と取得スクリプトを追加

`cd1f1bf` 2026-09-06 07:49 — 2 ファイル ／ +58 −0

- `tools/fetch_vendor.py` +39 −0
- `web/vendor/README.md` +19 −0

### 7. 匿名化加工済みデータ（研究用）に対応

`da86f9f` 2026-09-06 07:54 — 21 ファイル ／ +441 −89

- `templates/official_v1.json` +104 −52
- `web/js/anonymize.js` +71 −0
- `python/ikensho_ocr/anonymize.py` +56 −0
- `templates/sample_v1.json` +52 −0
- `web/js/review.js` +34 −6
- `schema/ikensho.schema.json` +15 −5
- `tools/form_definition.py` +10 −10
- `DEVNOTES.md` +19 −0
- `README.md` +19 −0
- `python/ikensho_ocr/extract.py` +12 −2
- `web/js/pipeline.js` +12 −2
- `web/js/exporters.js` +8 −4
- `python/ikensho_ocr/export.py` +6 −3
- `web/index.html` +7 −0
- `python/ikensho_ocr/cli.py` +4 −1
- ほか 6 ファイル +12 −4

### 8. 様式間のテキスト欄転写を、行ごとの局所写像に置き換え

`4b190ad` 2026-09-06 08:00 — 7 ファイル ／ +385 −343

- `templates/sample_v1.json` +176 −288
- `tools/build_consensus_template.py` +153 −40
- `DEVNOTES.md` +27 −10
- `python/ikensho_ocr/extract.py` +9 −3
- `web/js/pipeline.js` +8 −2
- `README.md` +6 −0
- `web/js/review.js` +6 −0

### 9. OCR精度の改善と、OS別の配布手段を整備

`8423224` 2026-09-06 08:33 — 27 ファイル ／ +1,477 −72

- `python/ikensho_ocr/ocr.py` +165 −27
- `docs/INSTALL.md` +186 −0
- `web/js/devnotes.js` +156 −0
- `python/ikensho_ocr/llm.py` +135 −0
- `DEVNOTES.md` +101 −1
- `README.md` +58 −14
- `packaging/windows/build.ps1` +72 −0
- `packaging/windows/ikensho.iss` +71 −0
- `web/js/pipeline.js` +58 −13
- `packaging/windows/README.md` +65 −0
- `tools/fetch_llm_model.py` +65 −0
- `python/ikensho_ocr/dictionaries.py` +55 −2
- `web/js/dicts.js` +52 −2
- `python/ikensho_ocr/extract.py` +37 −7
- `.github/workflows/windows-installer.yml` +37 −0
- ほか 12 ファイル +164 −6

### 10. テキスト欄の読み取り位置を修正し、確認画面を改善

`3a74bdc` 2026-09-06 09:14 — 13 ファイル ／ +1,792 −335

- `templates/sample_v1.json` +333 −220
- `tools/learn_text_regions.py` +377 −0
- `templates/official_v1.json` +156 −104
- `python/ikensho_ocr/proofread.py` +242 −0
- `templates/measured/sample_v1.json` +199 −0
- `tools/form_grid.py` +120 −0
- `tools/text_placement.py` +118 −0
- `web/js/review.js` +112 −1
- `tools/apply_placement.py` +102 −0
- `web/style.css` +19 −3
- `web/index.html` +8 −5
- `python/ikensho_ocr/extract.py` +3 −1
- `web/js/pipeline.js` +3 −1

### 11. 思考モードなしのQwenに変更し、OCR後の日本語チェックを追加

`e7306c1` 2026-09-06 09:24 — 6 ファイル ／ +174 −17

- `web/js/dicts.js` +74 −6
- `python/ikensho_ocr/llm.py` +38 −5
- `README.md` +23 −1
- `python/ikensho_ocr/extract.py` +19 −1
- `tools/fetch_llm_model.py` +12 −4
- `web/js/review.js` +8 −0

### 12. LLMを既定で有効化し、Docker配布とドキュメントページを整備

`32901b2` 2026-09-06 10:32 — 20 ファイル ／ +1,326 −220

- `docs/DEVELOPER.md` +434 −0
- `tools/build_docs_site.py` +234 −0
- `tools/build_sample_gallery.py` +175 −0
- `web/js/devnotes.js` +0 −156
- `DEVNOTES.md` +123 −2
- `docs/INSTALL.md` +93 −25
- `.github/workflows/docker-image.yml` +50 −0
- `python/ikensho_ocr/extract.py` +33 −7
- `packaging/Dockerfile` +28 −6
- `packaging/apache/htaccess.sample` +27 −0
- `python/ikensho_ocr/llm.py` +22 −5
- `web/index.html` +16 −10
- `README.md` +23 −2
- `packaging/docker-compose.yml` +23 −0
- `python/ikensho_ocr/cli.py` +11 −4
- ほか 5 ファイル +34 −3

### 13. 日付欄を数字入力にし、LLMモデルの選択・ダウンロードとモデル比較を追加

`290d765` 2026-09-06 10:49 — 23 ファイル ／ +1,003 −12

- `tools/benchmark_models.py` +172 −0
- `templates/official_v1.json` +156 −0
- `python/ikensho_ocr/dates.py` +110 −0
- `web/js/review.js` +102 −1
- `web/js/admin.js` +97 −0
- `python/ikensho_ocr/server.py` +86 −0
- `web/js/dates.js` +83 −0
- `docs/DEVELOPER.md` +43 −0
- `web/style.css` +25 −0
- `python/ikensho_ocr/extract.py` +18 −1
- `tools/form_definition.py` +12 −6
- `web/js/pipeline.js` +18 −0
- `DEVNOTES.md` +17 −0
- `web/index.html` +16 −0
- `README.md` +12 −1
- ほか 8 ファイル +36 −3

### 14. 日付欄は数字だけを読み、西暦に直した値を別に保存する

`f46cbe5` 2026-09-06 11:04 — 12 ファイル ／ +293 −38

- `python/ikensho_ocr/derive.py` +100 −0
- `web/js/exporters.js` +81 −8
- `DEVNOTES.md` +27 −1
- `python/ikensho_ocr/ocr.py` +20 −2
- `README.md` +15 −2
- `python/ikensho_ocr/export.py` +15 −1
- `templates/official_v1.json` +8 −8
- `python/ikensho_ocr/dates.py` +9 −3
- `schema/ikensho.schema.json` +6 −6
- `tools/form_definition.py` +6 −6
- `python/ikensho_ocr/extract.py` +3 −1
- `python/ikensho_ocr/charsets.py` +3 −0

### 15. 日付欄を様式に依存せず読み、確認画面と検証手段を整備

`94c0d6e` 2026-09-06 11:32 — 24 ファイル ／ +1,209 −47

- `python/ikensho_ocr/ocr.py` +209 −3
- `tools/fetch_hospitals.py` +205 −0
- `templates/official_v1.json` +173 −1
- `templates/sample_v1.json` +129 −9
- `tools/build_date_slots.py` +130 −0
- `python/ikensho_ocr/extract.py` +57 −7
- `dict/hospitals/index.json` +55 −0
- `web/js/review.js` +52 −0
- `tools/build_master_template.py` +41 −0
- `web/style.css` +35 −6
- `web/js/app.js` +29 −0
- `tools/apply_placement.py` +25 −0
- `python/ikensho_ocr/cli.py` +11 −5
- `python/ikensho_ocr/templates.py` +13 −2
- `tools/build_sample_gallery.py` +10 −1
- ほか 9 ファイル +35 −13

### 16. 電話番号と郵便番号の書式を整える

`b76d2b1` 2026-09-06 11:34 — 2 ファイル ／ +37 −2

- `python/ikensho_ocr/charsets.py` +24 −1
- `web/js/pipeline.js` +13 −1

### 17. レビューで見つかった重大な不具合を修正し、確定の状態を追加

`4004cd6` 2026-09-06 11:56 — 16 ファイル ／ +356 −114

- `web/js/review.js` +83 −17
- `python/ikensho_ocr/dictionaries.py` +43 −24
- `web/js/engine.js` +50 −9
- `python/ikensho_ocr/extract.py` +45 −12
- `web/js/dicts.js` +30 −24
- `DEVNOTES.md` +29 −0
- `python/ikensho_ocr/ocr.py` +24 −5
- `web/style.css` +15 −0
- `web/js/pipeline.js` +12 −2
- `python/ikensho_ocr/export.py` +7 −4
- `python/ikensho_ocr/align.py` +7 −3
- `python/ikensho_ocr/checkbox.py` +0 −9
- `web/js/dates.js` +7 −2
- `web/js/exporters.js` +3 −2
- `python/ikensho_ocr/proofread.py` +0 −1
- ほか 1 ファイル +1 −0

### 18. 確認画面を原本に近づけ、確定・削除の操作を追加

`d62d1ce` 2026-09-06 12:11 — 5 ファイル ／ +206 −20

- `web/js/review.js` +122 −9
- `web/style.css` +29 −9
- `python/ikensho_ocr/proofread.py` +28 −0
- `python/ikensho_ocr/extract.py` +20 −1
- `web/index.html` +7 −1

### 19. 拡大表示の横スクロール、音声入力、栄養留意点の位置修正

`a8876f1` 2026-09-06 12:16 — 7 ファイル ／ +203 −10

- `web/js/speech.js` +103 −0
- `web/js/review.js` +64 −1
- `web/style.css` +22 −4
- `web/index.html` +8 −0
- `templates/measured/sample_v1.json` +2 −2
- `templates/sample_v1.json` +2 −2
- `tools/build_standalone.py` +2 −1

### 20. 関連する項目をまとめて表示し、医療機関名を一覧から選べるようにした

`7e2735e` 2026-09-06 12:31 — 6 ファイル ／ +498 −126

- `schema/ikensho.schema.json` +186 −62
- `tools/form_definition.py` +124 −62
- `web/js/review.js` +157 −2
- `web/style.css` +27 −0
- `python/ikensho_ocr/schema.py` +3 −0
- `tools/build_web.py` +1 −0

### 21. 操作ログと利用者トークンを追加し、作業ログを残すようにした

`17e349a` 2026-09-06 13:59 — 12 ファイル ／ +1,398 −12

- `WORKLOG.md` +544 −0
- `web/js/oplog.js` +212 −0
- `tools/build_worklog.py` +183 −0
- `web/js/admin.js` +115 −0
- `web/js/session.js` +97 −0
- `web/js/review.js` +63 −4
- `DEVNOTES.md` +55 −0
- `docs/DEVELOPER.md` +41 −0
- `web/index.html` +40 −1
- `web/js/app.js` +28 −6
- `README.md` +18 −0
- `tools/build_standalone.py` +2 −1

### 22. 作業ログを最新のコミットに合わせた

`259d69f` 2026-09-06 13:59 — 1 ファイル ／ +5 −5

- `WORKLOG.md` +5 −5

### 23. 記述欄の左端を広げ、読めた文字数を書き込み量と突き合わせる

`a88cb78` 2026-09-06 14:19 — 9 ファイル ／ +552 −21

- `web/js/engine.js` +179 −1
- `python/ikensho_ocr/text_check.py` +149 −0
- `python/ikensho_ocr/textbox.py` +71 −0
- `DEVNOTES.md` +59 −0
- `python/ikensho_ocr/extract.py` +33 −7
- `README.md` +33 −5
- `web/js/pipeline.js` +20 −4
- `docs/DEVELOPER.md` +4 −2
- `web/index.html` +4 −2

### 24. 作業ログを更新

`78e8339` 2026-09-06 14:19 — 1 ファイル ／ +31 −9

- `WORKLOG.md` +31 −9

### 25. 該当箇所の拡大表示を掴んで横に動かせるようにした

`223c3be` 2026-09-06 14:24 — 3 ファイル ／ +64 −4

- `web/js/review.js` +49 −0
- `web/style.css` +14 −3
- `web/index.html` +1 −1

### 26. 作業ログを更新

`4d43fae` 2026-09-06 14:24 — 1 ファイル ／ +22 −6

- `WORKLOG.md` +22 −6

### 27. 2回目のレビューで見つかった不具合を修正

`6aba17f` 2026-09-06 14:53 — 14 ファイル ／ +579 −233

- `python/ikensho_ocr/extract.py` +125 −113
- `python/ikensho_ocr/text_check.py` +116 −34
- `web/js/engine.js` +91 −30
- `DEVNOTES.md` +47 −8
- `web/js/session.js` +41 −7
- `web/js/review.js` +28 −11
- `web/js/pipeline.js` +31 −6
- `python/ikensho_ocr/textbox.py` +23 −10
- `web/js/admin.js` +28 −4
- `web/js/app.js` +14 −7
- `web/js/oplog.js` +13 −2
- `web/js/exporters.js` +11 −0
- `python/ikensho_ocr/export.py` +6 −1
- `web/index.html` +5 −0

### 28. 医療機関名を一覧と突き合わせ、記述の1文字は空にする

`9bc8de8` 2026-09-06 15:14 — 6 ファイル ／ +368 −6

- `python/ikensho_ocr/hospitals.py` +172 −0
- `python/ikensho_ocr/extract.py` +93 −1
- `DEVNOTES.md` +47 −0
- `web/js/dicts.js` +23 −3
- `python/ikensho_ocr/dictionaries.py` +22 −2
- `web/js/pipeline.js` +11 −0

<!-- AUTO_END -->
