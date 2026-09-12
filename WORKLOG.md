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
| 「該当箇所」（拡大プレビュー）を横スクロール可能に | ❌ | 着手直後（ISSUE #17） |
| 医療機関リストを厚労省から都道府県ごとに | △ | 47都道府県ぶんを取得（30）。厚生局の一覧ページが404の分は都道府県サイトから補う |
| 医療機関名をLLMで気を効かせる | △ | 一覧からの選択は実装（20）。LLMでの補正は未 |
| ローカルで動く1つのファイル | △ | 単一HTMLは作成済（3）。ただし `file://` ではブラウザの制約でOCRを起動できず、チェック欄の読み取りのみ（ISSUE #16） |
| チェック欄の「枠外はみ出し」の印 | △ | 正解データで45.6%。隣の手書きと見分けが付かない（ISSUE #55） |
| 源内への実際の登録 | ❌ | 受け口は用意済み・既定は閉。開くと患者情報が端末の外に出るため、運用の取り決めが先（開発メモ 8.5.5） |
| 実データでの検証 | ❌ | いまの数字は生成された正解データに対するもの（開発メモ 8.5.3） |
| 汚れの多いスキャンでのチェックの誤検出 | △ | 誤検出117件のうち79件が3通に集中（ISSUE #55） |

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
| 記述部分の最初が切れているので読む場所を左に広げて | ✅ | 25 |
| textのOCRのあと文字数や先頭・最後の文字を確認して精度を上げて | ✅ | 26 |
| 生年月日の「日」が取れていない | ✅ | 38 |
| 何もない欄は白のままで良い（`）`が残る件） | ✅ | 38 |
| **seigo の正解データを使って精度を上げて** | ✅ | 43（チェック 95.47%→99.08%） |
| **チェックの後ろの文字はWordで変わるのでOCRで読む／修正可能に** | ✅ | 44 |
| **VLMベースのものも作る（ボタンでOCRを切り替え）** | ✅ | 46 |
| **PDFのフォーマットをベースにJSONを吐き出す（チェックは言葉で）** | ✅ | 45 |
| OCRの精度がイマイチ／前の方がよかった | ✅ | 57（チェック欄用の変更が文字欄にも効いていた。戻した） |
| 発症年月日など日だけがぬける | ✅ | 59、60（測ると日は94.1%で最良。悪いのは年 75.5%→78.1%） |
| 診断名はICDの近い場所から選ぶ | ✅ | 63 |
| 文字の解像度が低い場合の認識率 | ✅ | 64、66〜68（位置合わせの補間。75dpiで正解225→241件） |
| **源内（genai-web / genai-ai-api）の組み込み検討** | ✅ | 69〜（受け口のみ。既定は閉） |
| コードを最適化するagentにレビューさせる | ✅ | 70（8件指摘・全件修正） |
| 動作確認するユーザサイドのagentを動かす | ✅ | 71（9件指摘・全件修正） |

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
| Python版でも医療機関名を一覧で補正 | ✅ | 28 |
| 診療科しか入らない欄には診療科の辞書 | ✅ | 2 |
| 病名はICDも入れる | ✅ | 2 |
| できる限り選択＆文字補完 | ✅ | 3 |
| 病名を一覧から探すロジック | ✅ | 15 |
| CPUでも動くLLM（遅くならない程度） | ✅ | 11 |
| LLMを既定で動かす | ✅ | 12 |
| thinkingのないQwenに変更 | ✅ | 11 |
| モデルごとのベンチマークを開発ページに | ✅ | 13 |
| モデルを選べるダウンロードボタン | ✅ | 13 |
| OCRに特化した文字を読めるモデルを入れる | ✅ | 38（日本語専用 PP-OCRv4。文字正解率 85.3%→93.0%） |
| VLM（画像を見て答えるLLM）でも読めるように | ✅ | 46 |

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
| 褥瘡（部位：）は部位の後ろまで1つの項目に | ✅ | 24 |
| 「読み取り n / m 項目」の横のタグを押すと該当項目だけ表示 | ✅ | 34 |
| 確認・編集でキャッシュしている画像を消す機能 | ✅ | 36 |
| 開発メモとテンプレートなどの管理画面でメニューを分ける | ✅ | 36 |
| チェック欄の言葉を直せるように（管理画面） | ✅ | 44 |
| 読み取り方式をボタンで切り替え（画像処理＋OCR / VLM） | ✅ | 46 |
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
| 操作ログを残す | ✅ | 20 |
| 他の人の履歴が見えないようブラウザごとにトークンを発行 | ✅ | 22 |
| 医療機関リストを最新版にできるボタン | ✅ | 32 |
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
| 問題はISSUEに載せ、何をしたか分かるように | ✅ | GitHub Issues #1〜#55 |
| これまでのISSUEもすべて残す | ✅ | 閉じたものも本文を残している |
| ベンチマークも載せ、内容をPPTXに | ✅ | 30 |

---

<!-- AUTO_START -->

## 全体

- 期間: 2026-09-06 07:03 〜 2026-09-11 22:57
- コミット 71 件 / 追加 40,178 行 / 削除 5,404 行

### 今のコード量（コメント・空行を含む行数）

| 置き場所 | ファイル | 行 |
|---|---:|---:|
| ブラウザ版（確認・編集画面） | 21 | 8,217 |
| Python版（読み取り本体） | 25 | 6,291 |
| 生成・検証スクリプト | 32 | 6,523 |
| 配布（Docker・インストーラ） | 1 | 33 |
| **合計** | **79** | **21,064** |

### どこを何行いじったか（累計）

| 置き場所 | 追加 | 削除 | 触ったファイル |
|---|---:|---:|---:|
| ブラウザ版（確認・編集画面） | 8,898 | 573 | 28 |
| Python版（読み取り本体） | 6,800 | 505 | 26 |
| 生成・検証スクリプト | 6,722 | 304 | 33 |
| 様式テンプレート | 6,694 | 769 | 11 |
| その他（README・設定など） | 6,137 | 3,085 | 23 |
| 辞書 | 2,039 | 32 | 9 |
| 説明書 | 1,229 | 48 | 12 |
| 項目定義 | 1,227 | 82 | 1 |
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
| 29 | 2026-09-06 15:14 | 作業ログを更新 | 1 | 47 | 8 |
| 30 | 2026-09-06 16:46 | 医療機関一覧を47都道府県ぶん取得できるようにし、概要スライドを追加 | 8 | 1,235 | 123 |
| 31 | 2026-09-06 16:46 | 作業ログを更新 | 1 | 29 | 8 |
| 32 | 2026-09-06 17:00 | 管理画面から医療機関一覧を「最新版に更新」できるようにした | 10 | 311 | 13 |
| 33 | 2026-09-06 17:00 | 作業ログを更新 | 1 | 35 | 12 |
| 34 | 2026-09-06 17:36 | 集計の区分を押すと、その区分の項目だけを表示できるようにした | 4 | 74 | 17 |
| 35 | 2026-09-06 17:36 | 作業ログを更新 | 1 | 23 | 6 |
| 36 | 2026-09-06 21:52 | 元画像を破棄できるようにし、管理と開発メモのメニューを分けた | 7 | 165 | 19 |
| 37 | 2026-09-06 21:52 | 作業ログを更新 | 1 | 26 | 6 |
| 38 | 2026-09-08 21:20 | 文字を読むモデルを日本語専用に替え、精度を実測できるようにした | 27 | 1,832 | 64 |
| 39 | 2026-09-08 21:20 | 作業ログを更新 | 1 | 40 | 11 |
| 40 | 2026-09-08 21:23 | 管理画面で、ブラウザ側がこれから使うOCRモデルも表示する | 1 | 15 | 2 |
| 41 | 2026-09-08 21:25 | 単一HTML版に onnxruntime とOCRモデルを入れないようにした | 2 | 11 | 0 |
| 42 | 2026-09-08 21:48 | 作業ログを更新 | 1 | 30 | 8 |
| 43 | 2026-09-11 13:23 | 正解データ100通でチェック欄の判定を作り直した（95.47%→99.08%） | 15 | 1,773 | 74 |
| 44 | 2026-09-11 13:47 | チェック欄の後ろの言葉をOCRで確かめ、直せるようにした | 11 | 877 | 9 |
| 45 | 2026-09-11 13:52 | 様式の並びそのままのJSONを出せるようにした | 6 | 327 | 6 |
| 46 | 2026-09-11 14:07 | VLMで読む方式を足し、ボタンで切り替えられるようにした | 11 | 747 | 9 |
| 47 | 2026-09-11 14:09 | 作業ログを更新 | 1 | 113 | 16 |
| 48 | 2026-09-11 14:11 | 技術者向けドキュメントを今の実装に合わせた | 1 | 158 | 11 |
| 49 | 2026-09-11 14:14 | VLMの出力抑止に錠をかけ、ラベル読みの無駄な変数を消した | 2 | 15 | 5 |
| 50 | 2026-09-11 14:15 | ラベル正規化でハイフンが巨大な文字範囲になっていた | 1 | 4 | 2 |
| 51 | 2026-09-11 14:16 | 開発メモに3回目のレビューと残りの課題を追記 | 1 | 18 | 1 |
| 52 | 2026-09-11 14:47 | 確認画面に「この欄をVLMで読み直す」を足した | 6 | 137 | 4 |
| 53 | 2026-09-11 14:48 | VLMで日付欄を読み直したとき、年・月・日と西暦も作り直す | 1 | 11 | 0 |
| 54 | 2026-09-11 14:49 | 単一HTML版に labels.js が入っていなかった | 1 | 10 | 6 |
| 55 | 2026-09-11 14:49 | 開発メモの3回目のレビューに2件追記 | 1 | 5 | 0 |
| 56 | 2026-09-11 14:55 | 配置をスクリプトにした（パスワードを消してしまった件） | 3 | 56 | 0 |
| 57 | 2026-09-11 15:18 | 文字欄の差分だけ白紙の膨張を戻した（精度が落ちていた件） | 10 | 321 | 34 |
| 58 | 2026-09-11 15:19 | 公開したページからもVLMを選べるようにした | 2 | 58 | 0 |
| 59 | 2026-09-11 15:21 | ふりがな欄が必ず空になっていた／元年が読めなかった | 5 | 36 | 6 |
| 60 | 2026-09-11 15:27 | 日付の読み取りを測って調整できるようにした | 4 | 169 | 4 |
| 61 | 2026-09-11 15:31 | 開発メモに文字欄と日付の実測を追記 | 2 | 77 | 0 |
| 62 | 2026-09-11 15:38 | 身長・体重の読み落とされた小数点を戻す | 4 | 75 | 1 |
| 63 | 2026-09-11 15:52 | 診断名はICDの近い場所から選び、コードを出力に載せる | 7 | 155 | 7 |
| 64 | 2026-09-11 16:06 | 解像度の低い入力に備えて、切り抜きの引き伸ばし方を変えた | 4 | 63 | 12 |
| 65 | 2026-09-11 16:09 | 開発メモに ICD と低解像度対応、前処理の比較結果を追記 | 2 | 101 | 0 |
| 66 | 2026-09-11 16:43 | 検出が落ちた欄を全体1行で読み直す／輪郭立ては実測で悪化したので切った | 2 | 67 | 9 |
| 67 | 2026-09-11 17:33 | 医療機関名の欄から法人名を落とす／Lanczosの境目を実測で決めた | 5 | 87 | 2 |
| 68 | 2026-09-11 17:41 | 位置合わせの埋め方から Lanczos を外した（実測で差が無かった） | 2 | 27 | 10 |
| 69 | 2026-09-11 22:14 | 源内（デジタル庁の生成AI基盤）のAIアプリとして応答する受け口を足した | 3 | 309 | 3 |
| 70 | 2026-09-11 22:34 | レビューで見つかった8件を直した | 8 | 107 | 28 |
| 71 | 2026-09-11 22:57 | 利用者目線の動作確認で見つかった9件を直し、説明書を書いた | 9 | 330 | 40 |

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

### 29. 作業ログを更新

`a0229f9` 2026-09-06 15:14 — 1 ファイル ／ +47 −8

- `WORKLOG.md` +47 −8

### 30. 医療機関一覧を47都道府県ぶん取得できるようにし、概要スライドを追加

`96c6184` 2026-09-06 16:46 — 8 ファイル ／ +1,235 −123

- `tools/fetch_hospitals.py` +412 −96
- `tools/build_pptx.py` +482 −0
- `dict/hospitals/index.json` +261 −27
- `DEVNOTES.md` +46 −0
- `tools/build_docs_site.py` +18 −0
- `README.md` +9 −0
- `docs/DEVELOPER.md` +7 −0
- `"docs/\344\270\273\346\262\273\345\214\273\346\204\217\350\246\213\346\233\270\350\252\255\343\201\277\345\217\226\343\202\212_\346\246\202\350\246\201.pptx"` +0 −0

### 31. 作業ログを更新

`d28778a` 2026-09-06 16:46 — 1 ファイル ／ +29 −8

- `WORKLOG.md` +29 −8

### 32. 管理画面から医療機関一覧を「最新版に更新」できるようにした

`d485b45` 2026-09-06 17:00 — 10 ファイル ／ +311 −13

- `python/ikensho_ocr/server.py` +116 −0
- `web/js/admin.js` +101 −0
- `docs/DEVELOPER.md` +28 −0
- `tools/fetch_hospitals.py` +21 −4
- `web/index.html` +20 −0
- `README.md` +10 −0
- `dict/hospitals/index.json` +5 −5
- `tools/build_pptx.py` +5 −4
- `DEVNOTES.md` +5 −0
- `"docs/\344\270\273\346\262\273\345\214\273\346\204\217\350\246\213\346\233\270\350\252\255\343\201\277\345\217\226\343\202\212_\346\246\202\350\246\201.pptx"` +0 −0

### 33. 作業ログを更新

`555f537` 2026-09-06 17:00 — 1 ファイル ／ +35 −12

- `WORKLOG.md` +35 −12

### 34. 集計の区分を押すと、その区分の項目だけを表示できるようにした

`91e54c1` 2026-09-06 17:36 — 4 ファイル ／ +74 −17

- `web/js/review.js` +62 −17
- `web/style.css` +6 −0
- `DEVNOTES.md` +5 −0
- `README.md` +1 −0

### 35. 作業ログを更新

`1347868` 2026-09-06 17:36 — 1 ファイル ／ +23 −6

- `WORKLOG.md` +23 −6

### 36. 元画像を破棄できるようにし、管理と開発メモのメニューを分けた

`efbc19a` 2026-09-06 21:52 — 7 ファイル ／ +165 −19

- `web/js/review.js` +75 −2
- `web/index.html` +37 −17
- `web/js/app.js` +39 −0
- `DEVNOTES.md` +10 −0
- `web/style.css` +2 −0
- `README.md` +1 −0
- `web/js/oplog.js` +1 −0

### 37. 作業ログを更新

`1dba80d` 2026-09-06 21:52 — 1 ファイル ／ +26 −6

- `WORKLOG.md` +26 −6

### 38. 文字を読むモデルを日本語専用に替え、精度を実測できるようにした

`d9ec708` 2026-09-08 21:20 — 27 ファイル ／ +1,832 −64

- `tools/benchmark_ocr.py` +291 −0
- `web/js/ppocr.js` +225 −0
- `tools/test_web_ocr.py` +134 −0
- `tools/fetch_ocr_model.py` +128 −0
- `python/ikensho_ocr/server.py` +127 −0
- `tools/make_ocr_truth_sheet.py` +123 −0
- `DEVNOTES.md` +115 −0
- `python/ikensho_ocr/ocr.py` +94 −12
- `web/js/admin.js` +86 −0
- `bench/ocr_truth.json` +82 −0
- `web/js/pipeline.js` +64 −17
- `web/vendor/ort-wasm-simd-threaded.mjs` +59 −0
- `python/ikensho_ocr/textbox.py` +50 −0
- `docs/DEVELOPER.md` +48 −0
- `tools/build_pptx.py` +27 −21
- ほか 12 ファイル +179 −14

### 39. 作業ログを更新

`2ca4f92` 2026-09-08 21:20 — 1 ファイル ／ +40 −11

- `WORKLOG.md` +40 −11

### 40. 管理画面で、ブラウザ側がこれから使うOCRモデルも表示する

`ec11a3c` 2026-09-08 21:23 — 1 ファイル ／ +15 −2

- `web/js/admin.js` +15 −2

### 41. 単一HTML版に onnxruntime とOCRモデルを入れないようにした

`7a1bbf2` 2026-09-08 21:25 — 2 ファイル ／ +11 −0

- `DEVNOTES.md` +6 −0
- `tools/build_standalone.py` +5 −0

### 42. 作業ログを更新

`69b010b` 2026-09-08 21:48 — 1 ファイル ／ +30 −8

- `WORKLOG.md` +30 −8

### 43. 正解データ100通でチェック欄の判定を作り直した（95.47%→99.08%）

`8121bed` 2026-09-11 13:23 — 15 ファイル ／ +1,773 −74

- `tools/benchmark_seigo.py` +346 −0
- `tools/tune_checkbox.py` +327 −0
- `web/js/engine.js` +292 −14
- `web/js/ppocr.js` +230 −15
- `python/ikensho_ocr/checkbox.py` +200 −20
- `DEVNOTES.md` +168 −1
- `web/js/pipeline.js` +95 −6
- `python/ikensho_ocr/dates.py` +33 −7
- `web/js/dates.js` +25 −4
- `docs/DEVELOPER.md` +26 −0
- `tools/build_web.py` +10 −4
- `python/ikensho_ocr/text_check.py` +10 −1
- `tools/fetch_ocr_model.py` +5 −1
- `.gitignore` +4 −0
- `README.md` +2 −1

### 44. チェック欄の後ろの言葉をOCRで確かめ、直せるようにした

`acf9698` 2026-09-11 13:47 — 11 ファイル ／ +877 −9

- `python/ikensho_ocr/labels.py` +276 −0
- `web/js/labels.js` +210 −0
- `web/js/admin.js` +121 −0
- `web/js/pipeline.js` +75 −1
- `DEVNOTES.md` +59 −0
- `python/ikensho_ocr/extract.py` +50 −3
- `web/js/review.js` +29 −5
- `web/index.html` +26 −0
- `python/ikensho_ocr/server.py` +23 −0
- `web/style.css` +5 −0
- `python/ikensho_ocr/cli.py` +3 −0

### 45. 様式の並びそのままのJSONを出せるようにした

`edda6e9` 2026-09-11 13:52 — 6 ファイル ／ +327 −6

- `python/ikensho_ocr/export.py` +136 −0
- `web/js/exporters.js` +123 −1
- `DEVNOTES.md` +46 −0
- `web/js/app.js` +9 −3
- `python/ikensho_ocr/cli.py` +8 −2
- `web/index.html` +5 −0

### 46. VLMで読む方式を足し、ボタンで切り替えられるようにした

`9cbfbe3` 2026-09-11 14:07 — 11 ファイル ／ +747 −9

- `python/ikensho_ocr/vlm.py` +327 −0
- `tools/fetch_vlm_model.py` +111 −0
- `DEVNOTES.md` +70 −0
- `web/js/pipeline.js` +57 −6
- `python/ikensho_ocr/server.py` +62 −0
- `web/js/app.js` +51 −0
- `README.md` +28 −1
- `web/index.html` +16 −0
- `python/ikensho_ocr/ocr.py` +15 −0
- `python/ikensho_ocr/cli.py` +4 −2
- `web/style.css` +6 −0

### 47. 作業ログを更新

`dfc048b` 2026-09-11 14:09 — 1 ファイル ／ +113 −16

- `WORKLOG.md` +113 −16

### 48. 技術者向けドキュメントを今の実装に合わせた

`1216387` 2026-09-11 14:11 — 1 ファイル ／ +158 −11

- `docs/DEVELOPER.md` +158 −11

### 49. VLMの出力抑止に錠をかけ、ラベル読みの無駄な変数を消した

`eae44f5` 2026-09-11 14:14 — 2 ファイル ／ +15 −5

- `python/ikensho_ocr/vlm.py` +13 −0
- `python/ikensho_ocr/labels.py` +2 −5

### 50. ラベル正規化でハイフンが巨大な文字範囲になっていた

`152ee44` 2026-09-11 14:15 — 1 ファイル ／ +4 −2

- `python/ikensho_ocr/labels.py` +4 −2

### 51. 開発メモに3回目のレビューと残りの課題を追記

`d8f057b` 2026-09-11 14:16 — 1 ファイル ／ +18 −1

- `DEVNOTES.md` +18 −1

### 52. 確認画面に「この欄をVLMで読み直す」を足した

`6c44f6b` 2026-09-11 14:47 — 6 ファイル ／ +137 −4

- `web/js/review.js` +95 −0
- `DEVNOTES.md` +18 −0
- `README.md` +10 −3
- `docs/DEVELOPER.md` +5 −0
- `web/index.html` +5 −0
- `web/js/app.js` +4 −1

### 53. VLMで日付欄を読み直したとき、年・月・日と西暦も作り直す

`13100ef` 2026-09-11 14:48 — 1 ファイル ／ +11 −0

- `web/js/review.js` +11 −0

### 54. 単一HTML版に labels.js が入っていなかった

`01c48d1` 2026-09-11 14:49 — 1 ファイル ／ +10 −6

- `tools/build_standalone.py` +10 −6

### 55. 開発メモの3回目のレビューに2件追記

`69721a2` 2026-09-11 14:49 — 1 ファイル ／ +5 −0

- `DEVNOTES.md` +5 −0

### 56. 配置をスクリプトにした（パスワードを消してしまった件）

`991f135` 2026-09-11 14:55 — 3 ファイル ／ +56 −0

- `tools/deploy_web.sh` +36 −0
- `docs/DEVELOPER.md` +14 −0
- `DEVNOTES.md` +6 −0

### 57. 文字欄の差分だけ白紙の膨張を戻した（精度が落ちていた件）

`586d9a7` 2026-09-11 15:18 — 10 ファイル ／ +321 −34

- `tools/benchmark_dates.py` +133 −0
- `web/js/app.js` +60 −18
- `python/ikensho_ocr/server.py` +33 −1
- `web/index.html` +27 −0
- `web/js/pipeline.js` +23 −1
- `web/js/engine.js` +14 −6
- `python/ikensho_ocr/checkbox.py` +11 −3
- `python/ikensho_ocr/cli.py` +9 −1
- `python/ikensho_ocr/text_check.py` +8 −2
- `python/ikensho_ocr/textbox.py` +3 −2

### 58. 公開したページからもVLMを選べるようにした

`22293d5` 2026-09-11 15:19 — 2 ファイル ／ +58 −0

- `web/js/admin.js` +54 −0
- `web/style.css` +4 −0

### 59. ふりがな欄が必ず空になっていた／元年が読めなかった

`2375beb` 2026-09-11 15:21 — 5 ファイル ／ +36 −6

- `web/js/dates.js` +12 −2
- `python/ikensho_ocr/dates.py` +9 −2
- `web/js/pipeline.js` +6 −1
- `python/ikensho_ocr/charsets.py` +5 −1
- `python/ikensho_ocr/ocr.py` +4 −0

### 60. 日付の読み取りを測って調整できるようにした

`796de10` 2026-09-11 15:27 — 4 ファイル ／ +169 −4

- `tools/test_web_dates.py` +145 −0
- `python/ikensho_ocr/ocr.py` +12 −2
- `tools/benchmark_dates.py` +7 −1
- `tools/benchmark_seigo.py` +5 −1

### 61. 開発メモに文字欄と日付の実測を追記

`8f0efae` 2026-09-11 15:31 — 2 ファイル ／ +77 −0

- `DEVNOTES.md` +59 −0
- `docs/DEVELOPER.md` +18 −0

### 62. 身長・体重の読み落とされた小数点を戻す

`d3e6891` 2026-09-11 15:38 — 4 ファイル ／ +75 −1

- `python/ikensho_ocr/proofread.py` +35 −0
- `web/js/dicts.js` +24 −1
- `python/ikensho_ocr/extract.py` +8 −0
- `web/js/pipeline.js` +8 −0

### 63. 診断名はICDの近い場所から選び、コードを出力に載せる

`545a311` 2026-09-11 15:52 — 7 ファイル ／ +155 −7

- `python/ikensho_ocr/dictionaries.py` +47 −4
- `web/js/dicts.js` +37 −3
- `web/js/exporters.js` +26 −0
- `python/ikensho_ocr/derive.py` +13 −0
- `web/js/pipeline.js` +12 −0
- `python/ikensho_ocr/extract.py` +11 −0
- `python/ikensho_ocr/export.py` +9 −0

### 64. 解像度の低い入力に備えて、切り抜きの引き伸ばし方を変えた

`39ea49f` 2026-09-11 16:06 — 4 ファイル ／ +63 −12

- `python/ikensho_ocr/ocr.py` +34 −7
- `web/js/ppocr.js` +19 −2
- `tools/benchmark_dates.py` +6 −2
- `tools/benchmark_seigo.py` +4 −1

### 65. 開発メモに ICD と低解像度対応、前処理の比較結果を追記

`4fcdac2` 2026-09-11 16:09 — 2 ファイル ／ +101 −0

- `DEVNOTES.md` +91 −0
- `docs/DEVELOPER.md` +10 −0

### 66. 検出が落ちた欄を全体1行で読み直す／輪郭立ては実測で悪化したので切った

`5864b4b` 2026-09-11 16:43 — 2 ファイル ／ +67 −9

- `python/ikensho_ocr/ocr.py` +64 −7
- `web/js/ppocr.js` +3 −2

### 67. 医療機関名の欄から法人名を落とす／Lanczosの境目を実測で決めた

`99e97a4` 2026-09-11 17:33 — 5 ファイル ／ +87 −2

- `python/ikensho_ocr/align.py` +28 −1
- `python/ikensho_ocr/proofread.py` +25 −0
- `web/js/dicts.js` +17 −1
- `web/js/pipeline.js` +9 −0
- `python/ikensho_ocr/extract.py` +8 −0

### 68. 位置合わせの埋め方から Lanczos を外した（実測で差が無かった）

`35df702` 2026-09-11 17:41 — 2 ファイル ／ +27 −10

- `python/ikensho_ocr/align.py` +15 −9
- `web/js/pipeline.js` +12 −1

### 69. 源内（デジタル庁の生成AI基盤）のAIアプリとして応答する受け口を足した

`5b6e5bd` 2026-09-11 22:14 — 3 ファイル ／ +309 −3

- `python/ikensho_ocr/gennai.py` +234 −0
- `python/ikensho_ocr/server.py` +69 −2
- `python/ikensho_ocr/cli.py` +6 −1

### 70. レビューで見つかった8件を直した

`5c25a4a` 2026-09-11 22:34 — 8 ファイル ／ +107 −28

- `python/ikensho_ocr/align.py` +27 −9
- `python/ikensho_ocr/gennai.py` +26 −1
- `web/js/pipeline.js` +18 −4
- `web/js/app.js` +13 −5
- `web/js/exporters.js` +5 −5
- `python/ikensho_ocr/proofread.py` +7 −1
- `web/js/dicts.js` +7 −1
- `python/ikensho_ocr/server.py` +4 −2

### 71. 利用者目線の動作確認で見つかった9件を直し、説明書を書いた

`5708892` 2026-09-11 22:57 — 9 ファイル ／ +330 −40

- `docs/DEVELOPER.md` +84 −0
- `python/ikensho_ocr/gennai.py` +57 −10
- `README.md` +64 −0
- `python/ikensho_ocr/server.py` +46 −15
- `DEVNOTES.md` +31 −0
- `python/ikensho_ocr/llm.py` +19 −9
- `python/ikensho_ocr/anonymize.py` +20 −5
- `python/ikensho_ocr/cli.py` +6 −1
- `docs/INSTALL.md` +3 −0

<!-- AUTO_END -->
