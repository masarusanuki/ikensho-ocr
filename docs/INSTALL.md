# インストール手順

配布のしかたは3通りあります。用途に合わせて選んでください。

| | 対象 | 導入 | OCR精度 | 一括処理 |
|---|---|---|---|---|
| **A. ブラウザ版** | 誰でも | **不要** | 中（tesseract.js） | 画面から数十件 |
| **B. Docker** | **Windows / macOS / Linux 共通** | Docker のみ | 高 | 数千件 |
| **C. Python版** | Rocky / Ubuntu / macOS | pip + tesseract | 高 | 数千件 |

**OSごとに手順を分けたくない場合は B（Docker）が一番簡単です。**
Python も tesseract もイメージに入っているため、利用者側の準備は Docker だけです。

> どの方法でも、**チェックボックス186個の読み取り精度は同じ**です（OCRを使わないため）。
> 違いが出るのは氏名・病名などのテキスト欄だけです。

---

## A. ブラウザ版（インストール不要）

配布したい相手の環境を問いません。

- **単一ファイル版** … `ikensho-standalone.html` を渡すだけ。
  ダブルクリックで開き、オフラインで動作します。USBメモリでの配布も可能です。

  > ファイルを直接開いた場合、ブラウザのセキュリティ制約により**テキスト欄のOCRは使えません**
  > （自動で無効になり、画面に説明が出ます）。
  > **チェックボックス186項目の読み取りはすべて動作します**（全項目の約8割）。
  > テキスト欄も自動で読みたい場合は、下の Web版 か Windows版をお使いください。
- **Web版** … `dist/web/` をWebサーバに置きます。サーバ側の処理は不要です。
  スマートフォン・タブレットからも同じURLで使えます。

```bash
python3 tools/build_web.py                       # dist/web/ を作る
python3 tools/build_standalone.py                # dist/ikensho-standalone.html を作る
```

処理は端末内で完結し、患者情報は外部に送信されません。

---

## B. Docker（Windows / macOS / Linux 共通）

**利用者側に必要なのは Docker だけです。** Python も tesseract（日本語OCR）も
イメージに含まれているため、OSごとの手順の違いがありません。

### B-1. Docker を入れる

| OS | 入手先 |
|---|---|
| Windows | [Docker Desktop](https://www.docker.com/products/docker-desktop/)（WSL2 が必要。インストーラが案内します） |
| macOS | [Docker Desktop](https://www.docker.com/products/docker-desktop/) |
| Rocky / RHEL | `sudo dnf install -y docker podman-docker && sudo systemctl enable --now docker` |
| Ubuntu / Debian | `sudo apt install -y docker.io docker-compose-v2 && sudo systemctl enable --now docker` |

### B-2. 起動する

```bash
git clone https://github.com/masarusanuki/ikensho-ocr.git
cd ikensho-ocr
docker compose -f packaging/docker-compose.yml up
```

ブラウザで **http://localhost:8765** を開けば使えます。
初回はイメージの構築に5〜10分かかります。2回目以降はすぐ立ち上がります。

止めるときは `Ctrl+C`、後片付けは次のとおり。

```bash
docker compose -f packaging/docker-compose.yml down
```

### B-3. 公開イメージを使う（ビルド不要）

タグを打つと GitHub Actions がイメージを公開します
（[.github/workflows/docker-image.yml](../.github/workflows/docker-image.yml)）。
公開後は、リポジトリを取得しなくても1行で動きます。

```bash
docker run --rm -p 8765:8765 ghcr.io/masarusanuki/ikensho-ocr:latest
```

Windows の PowerShell でも同じコマンドで動きます。

### B-4. 大量のファイルをまとめて処理する

`scans` フォルダにPDFを入れて、次を実行します。

```bash
# Linux / macOS
docker run --rm -v "$PWD/scans:/data" ghcr.io/masarusanuki/ikensho-ocr \
    extract '/data/*.pdf' --csv /data/out.csv --json /data/out.json
```

```powershell
# Windows PowerShell
docker run --rm -v "${PWD}\scans:/data" ghcr.io/masarusanuki/ikensho-ocr `
    extract '/data/*.pdf' --csv /data/out.csv --json /data/out.json
```

結果は `scans/out.csv` と `scans/out.json` に出ます。

### B-5. LLM による候補提示を使う（任意）

GGUFモデルを `models/` に置いて起動すると、自動で有効になります。

```bash
python3 tools/fetch_llm_model.py         # models/ にモデルを取得
docker compose -f packaging/docker-compose.yml up
```

`docker-compose.yml` が `models/` をコンテナに渡します。

---

## C. Python版（Rocky Linux / Ubuntu / macOS）

### C-1. Rocky Linux 9 / RHEL 9 / AlmaLinux 9

```bash
sudo dnf install -y python3 python3-pip git
sudo dnf install -y tesseract tesseract-langpack-jpn      # 日本語OCR

git clone https://github.com/masarusanuki/ikensho-ocr.git
cd ikensho-ocr
python3 -m venv .venv && source .venv/bin/activate
pip install -e python
```

`tesseract-langpack-jpn` が見つからない場合は EPEL を有効にしてください。

```bash
sudo dnf install -y epel-release && sudo dnf install -y tesseract-langpack-jpn
```

### C-2. Ubuntu 22.04 / 24.04 / Debian 12

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv git
sudo apt install -y tesseract-ocr tesseract-ocr-jpn        # 日本語OCR

git clone https://github.com/masarusanuki/ikensho-ocr.git
cd ikensho-ocr
python3 -m venv .venv && source .venv/bin/activate
pip install -e python
```

### C-3. macOS（Intel / Apple Silicon 共通）

```bash
brew install python git
brew install tesseract tesseract-lang                      # 日本語を含む全言語

git clone https://github.com/masarusanuki/ikensho-ocr.git
cd ikensho-ocr
python3 -m venv .venv && source .venv/bin/activate
pip install -e python
```

Homebrew が未導入の場合:
`/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"`

### C-4. 導入確認（共通）

```bash
ikensho info
```

```
ikensho-ocr 0.1.0
項目定義: v1.0.0 / 107 項目
様式テンプレート:
  - official_v1: 主治医意見書（厚生労働省 標準様式） / 2ページ / チェックボックス186個 / テキスト欄52個
利用可能なOCRエンジン: tesseract, rapidocr, none
```

`利用可能なOCRエンジン` に `tesseract` が出れば日本語OCRが使えています。

### C-5. 追加のOCRエンジン（任意）

```bash
pip install "ikensho-ocr[ocr] @ ./python"     # RapidOCR を追加
```

tesseract と RapidOCR は得意分野が違います（tesseract は印刷された漢字と長文、
RapidOCR は短い欄と数字）。両方入れて `--engine ensemble` を指定すると、
項目ごとに良い方が自動で採用されます。処理時間は 1〜2 割増えます。

### C-6. 読み取り候補の提示にLLMを使う（任意・CPUで動作）

**候補を出すだけで、値は自動確定しません**（理由は README を参照）。
まずは辞書照合で足りることが多いので、読み取りが厳しい様式がある場合にだけ導入してください。

```bash
# コンパイラは不要。ビルド済みのCPU用wheelを使う
pip install --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu llama-cpp-python
python3 tools/fetch_llm_model.py --list     # 選べるモデルを表示
python3 tools/fetch_llm_model.py            # 既定（約1.1GB）を取得
ikensho extract scans/*.pdf --llm --csv out.csv
```

導入状況は `ikensho info` で確認できます。

## D. Windows インストーラ（Docker を使えない場合）

社内規程などで Docker を入れられない場合の選択肢です。
Python も tesseract も同梱するため、利用者側の作業はインストーラの実行だけです。

### D-1. 利用者の手順

1. `ikensho-ocr-setup-x.y.z.exe` を実行します
2. 画面の指示に従ってインストールします（既定は `C:\Program Files\主治医意見書読み取り`）
3. スタートメニューの「主治医意見書 読み取り」を起動すると、
   ローカルサーバが立ち上がり既定のブラウザで画面が開きます

コマンドラインからも使えます（インストール時に PATH へ追加した場合）。

```
ikensho extract "C:\scans\*.pdf" --csv C:\scans\out.csv
```

### D-2. インストーラの作り方（配布側）

Windows マシンで次を実行します。詳細は
[packaging/windows/README.md](../packaging/windows/README.md) を見てください。

```powershell
cd packaging\windows
.\build.ps1
```

`ikensho-ocr-setup-x.y.z.exe` が `packaging\windows\dist\` にできます。

GitHub Actions でも自動生成できます（`.github/workflows/windows-installer.yml`）。
タグを打つとインストーラがビルドされ、リリースに添付されます。

```bash
git tag v0.1.0 && git push origin v0.1.0
```

---

## アンインストール

| | 方法 |
|---|---|
| ブラウザ版 | HTMLファイルを削除するだけ |
| Python版 | `pip uninstall ikensho-ocr`（tesseract はOSのパッケージ管理で削除） |
| Docker | `docker compose -f packaging/docker-compose.yml down --rmi all` |
| Windows インストーラ | 「アプリと機能」から「主治医意見書 読み取り」を削除 |

読み取り結果はブラウザ版では端末内（localStorage）に保存されます。
消す場合は画面の「保存・出力」から各件を削除するか、ブラウザのサイトデータを削除してください。
