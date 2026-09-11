# 技術者向けドキュメント

このページは実装を触る人向けです。使い方は [README](../README.md)、
設計の経緯と失敗した試みは [開発メモ](../DEVNOTES.md) にあります。

---

## 1. 全体像

```
入力（PDF / 画像 / カメラ）
  │
  ├─ imaging.py      PDF→画像化、用紙の四隅検出→台形補正、照明ムラの平坦化
  │
  ├─ align.py        ORB特徴点 + RANSAC で様式テンプレートへ射影変換
  │                  どの様式の何ページ目かを同時に判定
  │
  ├─ checkbox.py     白紙様式との差分でマークを抽出 → 186項目（OCR不要）
  │
  ├─ ocr.py          テキスト欄だけを切り出して OCR（エンジン差し替え可）
  │   ├ charsets.py  欄ごとの文字種ヒント（日付・電話・カナ）
  │   └ vlm.py       画像を見て答えるLLMで読む（任意・ボタンで切り替え）
  │
  ├─ labels.py       チェック欄の後ろの言葉を確かめる（様式が変わっていないか）
  │
  ├─ kanji_norm.py   簡体字・異体字を日本語常用字体へ
  ├─ proofread.py    日本語チェックと誤字訂正（規則ベース）
  ├─ dictionaries.py 医療辞書との照合（編集距離ベース）
  ├─ llm.py          小型LLMによる候補提示（任意・自動確定はしない）
  ├─ anonymize.py    匿名化加工済みデータの扱い
  │
  ├─ extract.py      上記を束ねて1件のレコードにする
  └─ export.py       JSON / CSV / 様式の形のJSON 出力
```

ブラウザ版は `web/js/` に同じ判定ロジックを持ちます。共有しているのは**データ**
（項目定義・様式テンプレート・辞書）で、これが唯一の正典です。

| Python | ブラウザ | 内容 |
|---|---|---|
| `align.py` | `engine.js` | 位置合わせ・様式判定 |
| `checkbox.py` | `engine.js` | チェックボックス判定 |
| `labels.py` | `labels.js` | チェック欄の後ろの言葉 |
| `ocr.upscale_for_ocr` | `ppocr.js` の `prepare` | 切り抜きの引き伸ばし（低解像度対応） |
| `dictionaries.py` `proofread.py` `kanji_norm.py` | `dicts.js` | 辞書照合・日本語チェック |
| `extract.py` | `pipeline.js` | 全体の流れ |
| `export.py` | `exporters.js` | 出力 |

---

## 2. 開発環境の用意

```bash
git clone https://github.com/masarusanuki/ikensho-ocr.git
cd ikensho-ocr
python3 -m venv .venv && source .venv/bin/activate

pip install -e python                      # 本体
pip install pdfplumber                     # テンプレート生成に必要
pip install rapidocr-onnxruntime           # OCRエンジン（任意）
pip install playwright && playwright install chromium   # ブラウザ版の自動テスト
```

日本語OCR（tesseract）は OS のパッケージで入れます。

```bash
sudo dnf install tesseract tesseract-langpack-jpn      # Rocky / RHEL
sudo apt install tesseract-ocr tesseract-ocr-jpn       # Ubuntu / Debian
brew install tesseract tesseract-lang                  # macOS
```

**注意**: `master/` と `sample/` は個人情報を含みうるため `.gitignore` で除外しています。
テンプレートを再生成するには、これらを手元に置いてください。

---

## 3. コマンド一覧

### 3.1 生成系（データを作り直す）

順番に意味があります。項目定義を変えたら 1 から通してください。

```bash
# 1. 項目マスタから、項目定義JSONと公式様式テンプレートを生成
#    （master/主医師意見書.pdf のテキストレイヤから □ の座標を自動抽出）
python3 tools/build_master_template.py

# 2. 医療辞書を生成（診療科・傷病名/ICD-10・部位・感染症ほか）
python3 tools/build_dictionaries.py

# 3. 様式の印刷文言を抽出（OCR結果から除去するために使う）
python3 tools/build_boilerplate.py

# 4. テキスト欄の座標を確定（チェックボックス基準の定義 + 様式ごとの実測）
python3 tools/apply_placement.py

# 5. Web版を組み立てる
python3 tools/build_web.py

# 6. 単一HTMLファイル版を作る（オフライン動作）
python3 tools/build_standalone.py
```

期待される出力（項目数が合わなければどこかが壊れています）。

```
チェックボックス 186 個 / 輪郭スナップ成功 186 (100.0%) / 推定 0
テキスト欄 52 個
問題: 0
```

### 3.2 検証系

```bash
# 動作環境と様式の状況
ikensho info

# テンプレート座標を画像に重ねて目視確認
python3 tools/preview_template.py templates/official_v1.json master/主医師意見書.pdf /tmp/tpl
python3 tools/preview_on_ref.py sample_v1 /tmp/sv1

# ブラウザ版を実際に動かして確認（スクリーンショットも出る）
python3 tools/test_web.py --files sample/ikensho_0068.pdf --shots docs/screenshots

# 概要スライド（PPTX）を作り直す
python3 tools/build_pptx.py

# 医療機関一覧を厚生労働省から取り直す（47都道府県 / 20分ほど）
python3 tools/fetch_hospitals.py
python3 tools/fetch_hospitals.py --bureaus kinki kyushu    # 局を絞る
python3 tools/fetch_vlm_model.py --list                    # VLM（任意）
python3 tools/fetch_vlm_model.py                           # 既定 Qwen2.5-VL 3B

# 作業ログ（WORKLOG.md）を git の履歴から作り直す
python3 tools/build_worklog.py
python3 tools/build_worklog.py --check     # 最新かどうかだけ調べる（要更新なら終了コード1）
```

### 3.3 読み取り

```bash
ikensho extract sample/*.pdf --json out.json --csv out.csv

ikensho extract sample/*.pdf --engine ensemble      # 精度重視（時間は1〜2割増）
ikensho extract sample/*.pdf --engine tesseract     # 速度重視
ikensho extract sample/*.pdf --no-llm               # LLM候補提示を切る（最速）
ikensho extract sample/*.pdf --no-labels            # チェック欄の言葉を確かめない（18秒速い）
ikensho extract sample/*.pdf --engine vlm           # 画像を見て答えるLLMで読む（遅い）
ikensho extract sample/*.pdf --form-json form.json  # 様式の並びそのままのJSON
ikensho extract sample/*.pdf --anonymized           # 匿名化加工済みデータとして扱う
ikensho extract sample/*.pdf --group file           # 1ファイル1件として扱う

ikensho serve                                       # 確認・編集画面をローカルで開く
```

`--group` の意味。

| 値 | 1件のまとめ方 |
|---|---|
| `pair`（既定） | PDFは1ファイル1件、画像は2枚で1件 |
| `file` | 1ファイル1件 |
| `all` | 渡した全ファイルで1件 |

---

## 4. 新しい様式を追加する

自治体ごとに様式が違う場合の手順です。**チェックボックスは自動で正確に取れます。
手を入れるのはテキスト欄だけ**で済みます。

### 4.1 元の様式PDFにテキストレイヤがある場合

Word などから作った PDF なら、`□` の座標をそのまま取れます。
`tools/build_master_template.py` を参考に、`MASTER` のパスを差し替えてください。

### 4.2 記入済みのスキャンしか無い場合

同一様式が **20枚以上** あると安定します。

```bash
# 位置合わせ済み画素の高パーセンタイル合成で「白紙の様式」を復元し、
# そこから四角形を検出してチェックボックス座標を作る
python3 tools/build_consensus_template.py \
    --glob 'scans/city_a/*.pdf' --id city_a_v1 --name 'A市様式'
```

期待される出力。

```
page1: チェックボックス 75 個 (期待 75)
page2: チェックボックス 111 個 (期待 111)
```

個数が合わない場合は行構成の比較が表示されるので、どの行がずれているか分かります。

```
! 個数不一致 — 行構成 検出=[4, 4, 1, 9, ...]
              マスター=[4, 5, 1, 9, ...]
! 行1: 検出4 個 / マスター5 個
```

パーセンタイルを変えると改善することがあります（既定90、範囲85〜93）。

```bash
python3 tools/build_consensus_template.py --glob '...' --id city_a_v1 --name '...' --percentile 88
```

### 4.3 テキスト欄の座標を決める

3段階です。上から順に試してください。

**(a) チェックボックス基準の定義で自動的に決まるもの**

`tools/text_placement.py` に「このチェックボックスの右」「この2つの間」という
相対的な定義があります。チェックボックスの座標はどの様式でも正確なので、
定義を書けば様式が変わっても使い回せます。数値は公式様式から自動較正済みです。

```bash
python3 tools/apply_placement.py city_a_v1
# → city_a_v1: 実測0 / チェックボックス基準19 / 暫定33
```

**(b) 記入済みサンプルから実測する**

記入済みサンプルを重ねて「実際に書かれている場所」を求め、罫線に合わせます。

```bash
# まず枠と記入位置を見る（書き込みはしない）
python3 tools/learn_text_regions.py --id city_a_v1 --glob 'scans/city_a/*.pdf' \
        --dry-run --preview /tmp/learn
# /tmp/learn_p1.png を開いて、赤=記入位置 と 枠 の対応を確認する
```

**(c) 実測値を書き留める**

自動で決まらない欄は `templates/measured/<様式ID>.json` に座標を書きます。
`(b)` のプレビュー画像から読み取れます。座標はページに対する割合
`[x, y, 幅, 高さ]` です。

```json
{
 "page1": {
  "doctor_name":   [0.188, 0.1650, 0.230, 0.0180],
  "clinic_name":   [0.188, 0.1856, 0.300, 0.0180]
 }
}
```

書いたら `apply_placement.py` を再実行します。`実測` の数が増えます。

**(d) 管理画面で微調整する**

アプリの「管理」→「様式テンプレート」で、項目を選んで画像上をドラッグすると
座標を直せます。「編集内容を書き出す」で JSON を保存し、`templates/` に置き換えます。

---

## 5. 精度を測る

正解ラベルが無いため、代用指標として
**「必ず記入される単一選択項目18個が1つ選ばれているか」** を見ています。

```bash
cat > /tmp/bench.py <<'PYEOF'
import sys, glob, collections
sys.path.insert(0, 'python')
from ikensho_ocr import schema as S, templates as T, extract as E
CORE = ['consent','report_count','other_dept_visit','symptom_stability',
        'adl_disabled','adl_dementia','short_term_memory','decision_ability',
        'communication_ability','bpsd_presence','other_psych_presence',
        'dominant_hand','outdoor_walking','wheelchair','eating',
        'nutrition_status','service_outlook','infection']
sc, tp = S.load_schema(), T.load_templates()
per = collections.defaultdict(collections.Counter)
for f in sorted(glob.glob('sample/*.pdf')):
    rec = E.extract_record([f], schema=sc, templates=tp, engine='none')
    c = per[rec.template_id or '不明']
    c['files'] += 1
    for cid in CORE:
        c['n'] += 1
        if rec.fields[cid]['value'] is not None: c['hit'] += 1
        if rec.fields[cid]['level'] == 'high':   c['high'] += 1
for t, c in sorted(per.items()):
    print(f"{t:12s} {c['files']:3d}件 検出率 {c['hit']/max(c['n'],1)*100:5.1f}% "
          f"確信度高 {c['high']/max(c['n'],1)*100:5.1f}%")
PYEOF
PYTHONPATH=python python3 /tmp/bench.py
```

**基準値**（これを下回ったら退行）。

| 様式 | 検出率 | 確信度「高」 |
|---|---|---|
| `official_v1` | 99.6% | 91.7% |
| `sample_v1` | 99.1% | 94.6% |

`--engine none` で測るのは、チェックボックス判定だけを見たいからです。
OCR を挟むと結果がエンジンに左右されて比較になりません。

---

## 5.1 正解データ（seigo）で測る

100通ぶんの正解データ一式（PDF 100件・チェック 18,600件・文字 3,924件・
印の種類13通り＋二重線で訂正47件）に対して測れます。

```bash
python3 tools/benchmark_seigo.py --jobs 6 --marks   # チェック欄（印の種類ごとも出す）
python3 tools/benchmark_seigo.py --jobs 6 --text    # 文字欄
python3 tools/benchmark_dates.py --limit 30 --jobs 6  # 日付を年・月・日に分けて
python3 tools/test_web_dates.py --limit 8           # ブラウザ版の日付（別実装）
python3 tools/tune_checkbox.py dump --jobs 6        # 枠ごとの測定値を書き出す（約60秒）
python3 tools/tune_checkbox.py eval                 # 規則を画像なしで試す
```

**日付はまとめた正解率で見ないこと。** 「日だけ抜ける」という外し方をするので、
`benchmark_dates.py` で年・月・日を別々に見ます。実測では
年 75.5% / 月 92.4% / 日 94.1% で、**いちばん悪いのは年**でした。

**ブラウザ版の日付は Python 版と別実装**（`pipeline.readDate`）なので、
Python 版を測っただけでは分かりません。`test_web_dates.py` で別に測ります。

切り抜きの前処理は環境変数で差し替えて比べられます。

```bash
IKENSHO_DENOISE=0 IKENSHO_DATE_H=96 python3 tools/benchmark_dates.py --limit 30 --jobs 6
```

`IKENSHO_DENOISE`（ノイズ取りの強さ。既定7）は**全部の欄に効く**ので、
変えるときは日付だけでなく `--text` も測ってください。

**前処理はいまの値が最良だと測ってあります**（開発メモ 7.4.3）。
弱めても大きくしても悪化しました。触るならこの比較を作り直してから決めてください。

解像度の低い入力は、低い dpi で読み込んで模擬できます。

```bash
IKENSHO_BENCH_DPI=100 python3 tools/benchmark_dates.py --limit 20 --jobs 6
```

`tune_checkbox.py dump` は 18,600 枠の測定値を `bench/seigo_features.json` に
落とします。**判定の規則を触るときは必ずこれを使ってください。**
以後の試行はこのファイルだけで回せるので、1回1分ではなく1回1秒で試せます。

いまの値（`--marks`）。

```
正解率       99.08%
見落とし      46 件 / 印あり 3,240 件（Recall 98.58%）
誤検出       117 件 / 印なし 15,352 件
訂正の誤り     8 件 / 二重線で消した箇所 47 件（正しく0にできた 39）
```

`seigo/` と `bench/seigo_features.json` はリポジトリに入れていません
（正解データは頂いたもの、特徴量は作り直せるため）。

---

## 6. しきい値

`python/ikensho_ocr/checkbox.py` と `web/js/engine.js` に同じ値があります。
アプリの「管理」→「判定のしきい値」からも調整できます（ブラウザ版のみ）。

判定は**書き方ごとに見る場所を分けた4つの見方のうち、いちばん強いもの**を採ります
（正解データ100通・18,600枠で調整。開発メモ 7.4）。

| 見方 | 定数 | 境界 | 拾う書き方 |
|---|---|---|---|
| `fill` | `EMPTY_MAX` 0.10 / `FILLED_MIN` 0.28 | 0.19 | 白紙様式が無いときの保険 |
| `ink` | `INK_EMPTY_MAX` 0.02 / `INK_FILLED_MIN` 0.06 | 0.04 | レ点・×・塗りつぶし・☑ など大半 |
| `ring` | `RING_EMPTY_MAX` 0.10 / `RING_FILLED_MIN` 0.30 | 0.20 | 枠を丸で囲む記入 |
| `out` | `OUT_EMPTY_MAX` 0.015 / `OUT_FILLED_MIN` 0.045 | 0.03 | 枠外にはみ出した印 |

`ring` は `RING_BIAS_MAX`（0.50）で左右の偏りを見ます。丸囲みは枠の周りがぐるりと
濃くなりますが、隣の字を拾っただけなら片側に偏るためです。
`out` は `OUT_EDGE_*`（枠の右端の濃さ）も併せて見ます。はみ出した印は枠に
掛かったまま外へ伸びますが、隣の手書きは枠に触れません。

二重線で消した箇所は別に見ます。

| 定数 | 既定 | 意味 |
|---|---|---|
| `BLANK_DILATE` | 5 | 白紙側のインクを太らせる幅（重ね合わせのずれを吸収） |
| `STRIKE_BANDS_MIN` | 1 | 枠を左右に突き抜ける長い横線の本数 |
| `STRIKE_ALL_BANDS_MIN` | 2 | 突き抜けを問わない本数（二重線なので2本） |
| `STRIKE_LEN_MIN` / `STRIKE_LEN_ALONE` | 1.8 / 2.2 | 線の長さ（枠幅比）。同じ項目に他の印があれば緩く |
| `STRIKE_SIDE` | 0.3 | 枠の左右どこまで出ていれば「突き抜けた」か |

そのほか。

| 定数 | 既定 | 意味 |
|---|---|---|
| `MIN_INLIERS` | 25 | 様式判定に必要な対応点数 |
| `CONF_HIGH` / `CONF_MID` | 0.80 / 0.50 | 確信度の色分けの境目 |

ブラウザ版の「管理」→「判定のしきい値」から調整できるのは `EMPTY_MAX` /
`FILLED_MIN` / `CONF_*` / `MIN_INLIERS` です。他は `checkbox.py` と
`engine.js` の定数を揃えて直してください。

---

## 7. OCR エンジン

### 7.0 認識モデル（日本語）

**文字を読むモデルは差し替えられる。** 既定の rapidocr は中国語向けなので、
日本語のモデルを入れると精度が大きく変わる。

```bash
python3 tools/fetch_ocr_model.py --list       # 選べるモデル
python3 tools/fetch_ocr_model.py              # 既定（japan_v4・約11MB）
python3 tools/fetch_ocr_model.py ppocrv5_server
```

`models/ocr/<名前>/` に置かれ、**あれば自動で使われる**（`ikensho info` で確認できる）。
モデルを指定する場合は `--engine rapidocr:japan_v4` のように書く。
`rapidocr:default` は同梱の中国語向けモデル。

管理画面（`ikensho serve`）の「OCR」からも取得できる。取得すると
ブラウザ版が読む場所にも自動で配られる（画面の再読み込みで反映）。

正解データで測った結果は下の表のとおり。測り方は
[開発メモ 4.1.3](devnotes.html) を参照。

<!-- OCR_BENCH_START -->

| エンジン | 文字正解率 | 完全一致 | 空欄の判定 | 拾い読み | 所要 |
|---|---:|---:|---:|---:|---:|
| rapidocr:japan_v4 | 93.0% | 60.0% | 95.5% | 0件 | 45.3秒 |
| tesseract | 85.3% | 54.0% | 81.8% | 2件 | 9.5秒 |
| rapidocr | 80.4% | 42.0% | 90.9% | 1件 | 55.9秒 |

（正解 72 項目・うち記入あり 50 項目。辞書補正まで通した値で比較。`python3 tools/benchmark_ocr.py --update-docs` で更新）
<!-- OCR_BENCH_END -->

ブラウザ版も**同じモデル・同じ設定**で動きます（`web/js/ppocr.js`）。
文字の位置を見つけるモデルも積んでいるため、実測はほぼ同じです。

| | 文字正解率 | 完全一致 | 空欄の判定 | 拾い読み | 1件あたり |
|---|---:|---:|---:|---:|---:|
| Python版 | 93.0% | 60.0% | 95.5% | 0件 | 約45秒 |
| ブラウザ版 | 93.2% | 60.0% | 100% | 0件 | 約22秒 |
| （参考）ブラウザ版 tesseract.js | 86.2% | 36.0% | 100% | 0件 | － |

```bash
# 正解データ（bench/ocr_truth.json）で測る
python3 tools/benchmark_ocr.py --raw                       # OCRの生読みで比較
python3 tools/benchmark_ocr.py --engines tesseract rapidocr:japan_v4
python3 tools/benchmark_ocr.py --detail                    # 欄ごとの違いも出す
python3 tools/benchmark_ocr.py --update-docs               # この表を更新する

# 正解データを作り足す（切り抜き一覧の画像を作って、目視で書き取る）
python3 tools/make_ocr_truth_sheet.py sample/A_type_綺麗.pdf --out /tmp/sheet

# ブラウザ版の精度を同じ正解データで測る
python3 tools/test_web_ocr.py --raw
```

### 7.0.1 ブラウザ版の作り

`web/js/ppocr.js` が onnxruntime-web でモデルを動かします。

1. 欄の切り抜きを作る（位置はテンプレートで分かっている）
2. **文字の位置を見つける**（DBNet。しきい値0.3 → 輪郭 → 外接矩形 →
   確からしさ0.5 → 少し広げる。値は rapidocr の `config.yaml` と同じ）
3. 見つけた枠を行ごとにまとめ、上から下・左から右の順に認識する
4. 前処理（高さ48・`(値/255-0.5)/0.5`）と CTC の復号
   （`['blank'] + 辞書 + [' ']`）は Python 版と同じ

**文字の位置を見つける処理は省けません。** 省くと、日付欄のように数字が
離れて並ぶ欄で罫線や元号の丸印まで数字として読みます
（実測で `8年11月20日` が `28年11月20日`）。経緯は開発メモ 4.1.7。

読めた文字は位置つきで返るので、日付欄の振り分けにも使えます。

### 7.1 エンジンの選び方

```bash
ikensho info      # 使えるエンジンを確認
```

| 指定 | 得意 | 備考 |
|---|---|---|
| `rapidocr:japan_v4` | 日本語全般 | **いちばん正確**（実測 5.節）。`auto` はこれを選ぶ |
| `rapidocr` | 短い欄、数字 | モデル未取得だと中国語向けになる |
| `tesseract` | 導入済みの環境向け | **測ると最も弱い**。かつて「最も正確」と書いていたのは誤り |
| `ensemble` | 上記を項目ごとに使い分け | 精度重視。時間は1〜2割増 |
| `mangaocr` | 手書き | **生成型。文章を作り出すので既定では使わない** |
| `vlm` / `vlm:<名前>` | 崩れた手書き | 画像を見て答えるLLM。1欄4〜18秒（7.2） |
| `auto`（既定） | — | 使えるものを1つ選ぶ（VLM は選ばない） |
| `none` | — | チェックボックスだけ読む |

**前処理は強めないでください。** Otsu二値化・罫線除去・切り詰めは全て試して
悪化しました（[開発メモ 4.1.2](../DEVNOTES.md)）。tesseract の LSTM は
グレースケールを自前で処理する前提です。

### 7.2 VLM（画像を見て答えるLLM）

```bash
python3 tools/fetch_vlm_model.py          # 既定 Qwen2.5-VL 3B（約3.1GB）
ikensho extract scans/*.pdf --engine vlm
```

ブラウザ版は `ikensho serve` で開いたときだけ使えます。読み取り画面の
「読み取り方式」で VLM を選ぶと、1欄ぶんの切り抜きを `POST /api/vlm-read` に
渡します。**画像はこの端末の Python プロセスに渡すだけで、外部には出ません。**

`vlm.py` は `ocr.get_engine()` と同じ口（`read()` / `read_tokens()`）に
合わせてあるので、辞書照合・検算といった後段はそのまま通ります。

**既定にはしません。** PP-OCR のほうが速く、測った精度も上です。
また VLM は**読めない画像からもそれらしい文字を作る**ため、次の歯止めが入っています。

- 「読めない場合は 空 とだけ出力」と明示して聞く
- 説明・前置き・引用符を機械的に落とす（`_clean()`）
- 欄の文字種（`charset`）で後から絞る
- **確信度を `CONF_CAP` = 0.55 で頭打ち**にする（自動確定させない）

VLM は文字の位置を返さないので、日付欄を年・月・日に振り分ける専用経路は
使えません。欄全体を読んで文字列から解析する経路に落ちます。

**1通まるごとを VLM で読むのは現実的ではありません**（テキスト欄52個 ×
1欄5〜20秒。実測で40分でも終わらなかった）。確認画面の
「**この欄をVLMで読み直す**」で、読めていない欄だけを指して読み直してください。
値に入れたあとも確信度は上げず（`level = low`）、操作ログに残すので戻せます。

モデルを足すときは `vlm.py` の `_HANDLERS` に、名前の一部と
llama-cpp-python のチャットハンドラ名の対応を書き足してください
（分からない場合は汎用の `MTMDChatHandler` に落ちます）。

---

## 8. LLM による候補提示

短い欄（傷病名・診療科など）は**候補を出すだけで、値は自動確定しません**。
記述欄（`経過及び治療内容` `特記すべき事項`）だけは**校正結果を自動で反映**し、
反映前の読みを `candidates` に `source: "raw"` として残します。
理由と制限は `python/ikensho_ocr/llm.py` の冒頭に書いてあります。

```bash
# コンパイラ不要。ビルド済みのCPU用wheelを使う
pip install --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu llama-cpp-python

python3 tools/fetch_llm_model.py --list    # 選べるモデル
python3 tools/fetch_llm_model.py           # 既定 Qwen3-4B-Instruct-2507（約2.4GB）
```

モデルが置かれていれば**既定で有効**になります。切るには `--no-llm`。
呼び出す欄は「辞書で決めきれず、候補があり、読み取り自体は成立している」ものに
絞っており、1件あたりの上限は `--llm-budget`（既定8）です。

用意しているモデルは**いずれも思考モードを持たない版**です。
Qwen3 は `Instruct-2507` が非思考版で、`Thinking` 版とは別物なので取り違えないこと。

`ikensho serve` で開いた画面の「管理」→「LLMモデル」から、
モデルを選んでダウンロードすることもできます（サーバ版のみ）。

### 8.1 モデルごとの比較

用途が「辞書で決めきれなかった欄に候補を出す」ことなので、測るのは次の3点。

- **正答率** … 正しい候補を選べたか
- **安全性** … 読み取り不能な文字列から病名を作り出さないか（**最優先**）
- **速度** … 1件あたりの所要時間

安全性を正答率と並べて測るのは、小型モデルが `回提 6四6` のような
無意味な入力から「脳梗塞」を自信ありげに出したことが実際にあったため。
診療情報では正答率より優先する。

<!-- MODEL_BENCH_START -->

| モデル | サイズ | 正答 | 安全（作り出さない） | 1件あたり |
|---|---|---|---|---|
| 辞書のみ（LLM不使用） | — | 9/12 | 4/4 | 即時 |
| Qwen3-4B-Instruct-2507-Q4_K_M.gguf | 2.3 GB | 11/12 | 4/4 | 1.30 秒 |
| qwen2.5-1.5b-instruct-q4_k_m.gguf | 1.0 GB | 10/12 | 4/4 | 0.50 秒 |
| qwen2.5-3b-instruct-q4_k_m.gguf | 2.0 GB | 10/12 | 4/4 | 1.01 秒 |

（16問。うち「候補を出してはいけない」問題が 4 問。`python3 tools/benchmark_models.py --update-docs` で更新）

<!-- MODEL_BENCH_END -->

```bash
python3 tools/benchmark_models.py                  # models/ 内の全モデルを比較
python3 tools/benchmark_models.py --update-docs    # この表を更新する
python3 tools/benchmark_models.py --models path/to/model.gguf
```

読みかた。

- **辞書だけでも 9/12 取れる。** 編集距離ベースの照合を入れた効果で、
  LLM が無くても大半は直る。LLM は「辞書に無い表記ゆれ」への保険
- 4B は 1.5B より 1問多く正答するが、**2.6倍遅く、サイズも2.3倍**。
  候補提示が目的なので既定は 1.5B にしている
- **安全性はどのモデルも 4/4。** 辞書内の語に限定し、OCR結果との文字の重なりを
  確かめ、3文字未満の手がかりでは聞かない、という制限をかけているため

---

## 9. 配布

```bash
python3 tools/build_web.py --out /var/www/html/<配置先>     # Web版
python3 tools/build_standalone.py --out /path/ikensho.html  # 単一HTMLファイル
python3 tools/build_docs_site.py --out <配置先>/docs        # ドキュメントページ
python3 tools/build_sample_gallery.py <配置先>/samples      # 動作確認用サンプル一覧
```

### 9.0 Docker（OSを問わない配布）

**Windows / macOS / Linux で同じ手順にできるので、これが本命です。**
Python も tesseract もイメージに入ります。

```bash
docker compose -f packaging/docker-compose.yml up          # 起動（http://localhost:8765）
docker compose -f packaging/docker-compose.yml down        # 停止
docker build -t ikensho-ocr -f packaging/Dockerfile .      # 手でビルドする場合
docker run --rm -v "$PWD/scans:/data" ikensho-ocr \
    extract '/data/*.pdf' --csv /data/out.csv              # 一括処理
```

タグを打つと GitHub Actions が `ghcr.io` にイメージを公開します
（[.github/workflows/docker-image.yml](../.github/workflows/docker-image.yml)）。
公開後はリポジトリを取得せずに動かせます。

```bash
git tag v0.1.0 && git push origin v0.1.0
docker run --rm -p 8765:8765 ghcr.io/masarusanuki/ikensho-ocr:latest
```

Windows インストーラ（Dockerを使えない場合）は
[packaging/windows/README.md](../packaging/windows/README.md)。
OS別の導入手順は [docs/INSTALL.md](INSTALL.md)。

### 9.0 公開先へ置く

```bash
python3 tools/build_web.py
python3 tools/build_standalone.py          # 単一HTML版も更新する場合
bash tools/deploy_web.sh                   # 既定: /var/www/html/test-deploy/kaigo_nintei
```

**`rsync --delete` を直に叩かないでください。** 配置先にしか無い
`.htaccess` / `.htpasswd` / `samples/` を消してしまい、
**サイトのパスワードが外れます**（実際に外しました）。
`deploy_web.sh` はこれらを除外し、置いたあとにパスワード設定の有無を確かめて、
無ければ終了コード2で止まります。

### 9.1 Web版にパスワードをかける（Apache）

```bash
DEPLOY=/var/www/html/<配置先>
htpasswd -cbB "$DEPLOY/.htpasswd" <ユーザー名> <パスワード>
chmod 644 "$DEPLOY/.htpasswd"        # Apache が読める必要がある
cp packaging/apache/htaccess.sample "$DEPLOY/.htaccess"
# .htaccess 内の AuthUserFile を実際のパスに直す
```

確認。

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://localhost/<配置先>/                 # 401
curl -s -o /dev/null -w '%{http_code}\n' -u user:pass http://localhost/<配置先>/    # 200
curl -s -o /dev/null -w '%{http_code}\n' -u user:pass http://localhost/<配置先>/.htpasswd  # 403
```

前提として `AllowOverride All` が必要です。

```bash
grep -n 'AllowOverride' /etc/httpd/conf/httpd.conf
```

**Basic認証は、HTTPのままだとID・パスワードが平文に近い形で流れます。
必ず HTTPS で運用してください。**

利用者を追加・変更するとき。

```bash
htpasswd -bB "$DEPLOY/.htpasswd" <ユーザー名> <パスワード>   # 追加・変更
htpasswd -D "$DEPLOY/.htpasswd" <ユーザー名>                # 削除
```

---

## 9.1.1 医療機関一覧の更新（管理画面）

管理画面の「医療機関一覧」に**最新版に更新**があります。
押すと厚生労働省の地方厚生局から取り直します（**十数分**かかります。
その間もほかの操作はできます）。

- **サーバ版（`ikensho serve`）でのみ出ます。** 静的配信ではパネルごと隠れます
- 取得後は配信フォルダ（`dist/web/data/dict/hospitals/`）にも自動で反映します
- 取得中にもう一度押しても、二重には走りません（409 を返します）
- 取れなかった都道府県は**前回の内容を残します**（更新の失敗で消えないように）

コマンドから実行する場合、局を絞れます。

```bash
python3 tools/fetch_hospitals.py                          # 全国（47都道府県）
python3 tools/fetch_hospitals.py --bureaus shikoku kyushu # 局を絞る
```

API で絞ることもできます（1局だけ落ちたときの取り直しに使えます）。

```bash
curl -X POST http://127.0.0.1:8765/api/hospitals/update \
     -H 'Content-Type: application/json' -d '{"bureaus":["shikoku"]}'
curl http://127.0.0.1:8765/api/hospitals    # 状況と進捗
```

---

## 9.2 操作ログと利用者トークン（運用）

読み取り結果と操作ログは**ブラウザの中だけ**にあり、サーバには送られません。
同じ端末を複数の人が使う場合に履歴が混ざらないよう、ブラウザごとに
トークンを発行して保存先を分けています。

| 保存先 | 中身 |
|---|---|
| `ikensho.records.v1.<トークン>` | 読み取り結果 |
| `ikensho.oplog.v1.<トークン>` | 操作ログ |
| `ikensho.settings.v1.<トークン>` | しきい値 |
| `ikensho.token.v1` | 今のトークン |

管理画面（「利用者」「操作ログ」）でできること。

- 今のトークンの確認・コピー
- **新しく発行**（それまでの履歴を切り離す。共用端末で使い終わったときに押す）
- 別の端末のトークンに切り替える
- 操作ログの要約・一覧の確認、JSON / CSV での保存、消去
- 「値も記録する」の切り替え

注意点。

- トークンは**認証ではありません。** 同じブラウザの localStorage を直接見られる
  相手には隠せません。サイト全体の保護は 9.1 の Basic 認証で行ってください
- 氏名・住所など `pii` を持つ項目は、ログに値を残さず文字数だけを記録します
- 「新しく発行」は履歴を**消しません**。元のトークンを入れ直せば戻ります。
  完全に消すには管理画面の「消去」を使ってください

ログの列（CSV）は `日時, 操作, 対象, 項目, 直す前, 直した後, 確信度, 補足`。
JSON には要約（`summary`）と全件（`entries`）が入り、`blen` / `alen` に
直す前後の文字数が入るので、伏せ字の項目でも修正量を数えられます。

---

## 9.3 チェック欄の後ろの言葉（`labels.py` / `labels.js`）

様式を Word で作り直すと、枠の並びは同じでも**後ろの文字が変わる**ことがあります。
読み取りのときに枠の右隣も OCR して確かめ、食い違いを画面に出します。

**読めた言葉はそのまま採りません。** 白紙様式（＝いちばん条件のよい画像）でも
完全一致は 66% で、そのまま使うと出力がかえって壊れます。
値に使う言葉は **管理画面で直した言葉 > 定義（スキーマ）の言葉** の順で決め、
読み取りは「食い違っているかもしれない」という合図に使います。

食い違いと判定する条件（`labels.resolve`）。

| 条件 | 定数 | 理由 |
|---|---|---|
| 読めた言葉が3文字以上 | `CHANGED_MIN_LEN` 3 | 「有」「無」「Ⅳ」は読み違えが多すぎる |
| 定義の言葉を含まない（逆も） | — | 隣の語や手書きまで一緒に読めることがある |
| 定義との似かたが 0.5 以下 | `CHANGED_MAX_SIM` 0.5 | difflib と同じ尺度 |
| 同じ項目の他の選択肢にも似ていない | — | 振り分けを誤っただけの場合を除く |

直す場所。

- ブラウザ: 管理画面「チェック欄の言葉」。保存先は `localStorage` の
  `ikensho.labels.v1`。**利用者トークンでは分けません**（人の情報ではなく様式の設定）
- Python: `templates/labels/<様式ID>.json`（`GET/POST /api/labels`）

速さのために、読み取り時は**印の付いた枠だけ**を読みます（`only=`）。
様式全体は管理画面の「白紙様式から読み直す」で読めます。
切るときは `--no-labels`、ブラウザは読み取り画面のチェックを外します。

---

## 9.4 様式の形のJSON

```bash
ikensho extract 意見書.pdf --form-json out.json
```
ブラウザ版は一覧画面の「様式の形のJSONで保存」。

意見書の並び（**節 → まとまり → 項目**）そのままに入れ子にしたもので、
**チェック欄は言葉で返します**（選択肢の言葉を全部並べ、それぞれに印の有無を付ける）。
キーが日本語なのは、この JSON をそのまま人が読むことを想定しているためです。
機械処理向けの平らな JSON は従来どおり `--json` で出せます。

実装は `export.record_to_form_json` / `exporters.toFormJson`。
**両方を直したら、同じ形になるか突き合わせてください**（キーの集合・節・項目数）。

---

## 10. よくある不具合

| 症状 | 原因と対処 |
|---|---|
| 「様式を判別できませんでした」 | 参照画像との対応点が足りない。`MIN_INLIERS` を下げるか、その様式のテンプレートを作る |
| チェックが読めない | 白紙様式（`templates/blanks/`）が無いか解像度が違う。テンプレートを再生成する |
| テキストが別の場所から読まれる | テキスト欄の座標が合っていない。第4章の手順で直す |
| 単一HTMLでOCRが動かない | `file://` はブラウザの制約でOCRを起動できない。自動で無効になる仕様。Web版を使う |
| Apache が 500 を返す | `.htpasswd` を Apache が読めていない。`chmod 644` |
| チェックボックスの個数が合わない | 行構成の比較が出力されるので、そこを見る（4.2） |
| チェック欄の言葉が「口内科」になる | 枠を白で塗る処理が効いていない。`labels.read_labels` の塗りつぶし範囲を見る |
| VLM が使えない | `models/vlm/` に本体と mmproj の2つが要る。`tools/fetch_vlm_model.py --list` で確認 |
| VLM の実行中に大量のログが出る | `vlm._silence()` を通っていない。`create_chat_completion` は必ず包む |

---

## 11. コードを直すときの約束

- **項目定義を増やすときは `tools/form_definition.py` だけを直す。**
  他は生成物です
- **同じ判定は Python とブラウザの両方に入れる。** 片方だけ直すと結果がずれます
- **精度に関わる変更をしたら、第5章のベンチマークを流す。** 基準値を下回らないこと
- **チェック欄の判定を触ったら `tools/tune_checkbox.py dump` → `benchmark_seigo.py` を流す。**
  正解率 99.08% / 誤検出 117 を下回らないこと（5.1）
- **ブラウザ版を触ったら `tools/test_web.py` を流す。** 目視だけで済ませないこと
- **`master/` `sample/` `models/` はコミットしない。** `.gitignore` で除外済みです
- **コミットしたら `python3 tools/build_worklog.py` を流す。**
  作業ログ（[WORKLOG.md](../WORKLOG.md)）に、どこを何行いじったかが残ります
