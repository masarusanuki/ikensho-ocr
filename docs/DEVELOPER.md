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
  │   └ charsets.py  欄ごとの文字種ヒント（日付・電話・カナ）
  │
  ├─ kanji_norm.py   簡体字・異体字を日本語常用字体へ
  ├─ proofread.py    日本語チェックと誤字訂正（規則ベース）
  ├─ dictionaries.py 医療辞書との照合（編集距離ベース）
  ├─ llm.py          小型LLMによる候補提示（任意・自動確定はしない）
  ├─ anonymize.py    匿名化加工済みデータの扱い
  │
  ├─ extract.py      上記を束ねて1件のレコードにする
  └─ export.py       JSON / CSV 出力
```

ブラウザ版は `web/js/` に同じ判定ロジックを持ちます。共有しているのは**データ**
（項目定義・様式テンプレート・辞書）で、これが唯一の正典です。

| Python | ブラウザ | 内容 |
|---|---|---|
| `align.py` | `engine.js` | 位置合わせ・様式判定 |
| `checkbox.py` | `engine.js` | チェックボックス判定 |
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
```

### 3.3 読み取り

```bash
ikensho extract sample/*.pdf --json out.json --csv out.csv

ikensho extract sample/*.pdf --engine ensemble      # 精度重視（時間は1〜2割増）
ikensho extract sample/*.pdf --engine tesseract     # 速度重視
ikensho extract sample/*.pdf --no-llm               # LLM候補提示を切る（最速）
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

## 6. しきい値

`python/ikensho_ocr/checkbox.py` と `web/js/engine.js` に同じ値があります。
アプリの「管理」→「判定のしきい値」からも調整できます（ブラウザ版のみ）。

| 定数 | 既定 | 意味 |
|---|---|---|
| `EMPTY_MAX` | 0.10 | 枠内インク率がこれ未満なら未チェック |
| `FILLED_MIN` | 0.28 | 枠内インク率がこれ以上ならチェック済み |
| `MARK_EMPTY_MAX` | 0.012 | 白紙との差分がこれ未満なら未記入 |
| `MARK_FILLED_MIN` | 0.030 | 白紙との差分がこれ以上なら記入あり |
| `MIN_INLIERS` | 25 | 様式判定に必要な対応点数 |
| `CONF_HIGH` / `CONF_MID` | 0.80 / 0.50 | 確信度の色分けの境目 |

判定は「枠内インク率」と「白紙との差分」の**大きい方**を採ります。
枠に収まったチェックは前者が、はみ出したレ点や枠を囲む丸印は後者が拾います。

---

## 7. OCR エンジン

```bash
ikensho info      # 使えるエンジンを確認
```

| 指定 | 得意 | 備考 |
|---|---|---|
| `tesseract` | 印刷された漢字、複数行の文章 | 最も正確。導入推奨 |
| `rapidocr` | 短い欄、数字 | pipのみで入る。中国語モデル |
| `ensemble` | 上記を項目ごとに使い分け | 精度重視。時間は1〜2割増 |
| `mangaocr` | 手書き | **生成型。文章を作り出すので既定では使わない** |
| `auto`（既定） | — | 使えるものを1つ選ぶ |
| `none` | — | チェックボックスだけ読む |

**前処理は強めないでください。** Otsu二値化・罫線除去・切り詰めは全て試して
悪化しました（[開発メモ 4.1.2](../DEVNOTES.md)）。tesseract の LSTM は
グレースケールを自前で処理する前提です。

---

## 8. LLM による候補提示

**候補を出すだけで、値は自動確定しません。** 理由と制限は
`python/ikensho_ocr/llm.py` の冒頭に書いてあります。

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

## 10. よくある不具合

| 症状 | 原因と対処 |
|---|---|
| 「様式を判別できませんでした」 | 参照画像との対応点が足りない。`MIN_INLIERS` を下げるか、その様式のテンプレートを作る |
| チェックが読めない | 白紙様式（`templates/blanks/`）が無いか解像度が違う。テンプレートを再生成する |
| テキストが別の場所から読まれる | テキスト欄の座標が合っていない。第4章の手順で直す |
| 単一HTMLでOCRが動かない | `file://` はブラウザの制約でOCRを起動できない。自動で無効になる仕様。Web版を使う |
| Apache が 500 を返す | `.htpasswd` を Apache が読めていない。`chmod 644` |
| チェックボックスの個数が合わない | 行構成の比較が出力されるので、そこを見る（4.2） |

---

## 11. コードを直すときの約束

- **項目定義を増やすときは `tools/form_definition.py` だけを直す。**
  他は生成物です
- **同じ判定は Python とブラウザの両方に入れる。** 片方だけ直すと結果がずれます
- **精度に関わる変更をしたら、第5章のベンチマークを流す。** 基準値を下回らないこと
- **ブラウザ版を触ったら `tools/test_web.py` を流す。** 目視だけで済ませないこと
- **`master/` `sample/` `models/` はコミットしない。** `.gitignore` で除外済みです
