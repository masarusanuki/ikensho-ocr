# インストール手順

配布のしかたは3通りあります。用途に合わせて選んでください。

| | 対象 | 導入 | OCR精度 | 一括処理 |
|---|---|---|---|---|
| **A. ブラウザ版** | 誰でも | **不要** | 中（tesseract.js） | 画面から数十件 |
| **B. Python版** | Rocky / Ubuntu / macOS | pip + tesseract | 高 | 数千件 |
| **C. Windows インストーラ** | Windows | インストーラ実行のみ | 高 | 数千件 |

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

## B. Python版（Rocky Linux / Ubuntu / macOS）

### B-1. Rocky Linux 9 / RHEL 9 / AlmaLinux 9

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

### B-2. Ubuntu 22.04 / 24.04 / Debian 12

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv git
sudo apt install -y tesseract-ocr tesseract-ocr-jpn        # 日本語OCR

git clone https://github.com/masarusanuki/ikensho-ocr.git
cd ikensho-ocr
python3 -m venv .venv && source .venv/bin/activate
pip install -e python
```

### B-3. macOS（Intel / Apple Silicon 共通）

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

### B-4. 導入確認（共通）

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

### B-5. 追加のOCRエンジン（任意）

```bash
pip install "ikensho-ocr[ocr] @ ./python"     # RapidOCR を追加
```

tesseract と RapidOCR は得意分野が違います（tesseract は印刷された漢字と長文、
RapidOCR は短い欄と数字）。両方入れて `--engine ensemble` を指定すると、
項目ごとに良い方が自動で採用されます。処理時間は 1〜2 割増えます。

### B-6. 読み取り候補の提示にLLMを使う（任意・CPUで動作）

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

### B-7. Docker（環境を汚したくない場合）

```bash
docker build -t ikensho-ocr -f packaging/Dockerfile .
docker run --rm -p 8765:8765 ikensho-ocr serve --host 0.0.0.0
docker run --rm -v "$PWD/scans:/data" ikensho-ocr extract '/data/*.pdf' --csv /data/out.csv
```

---

## C. Windows（インストーラ）

利用者側の作業はインストーラの実行だけです。Python も tesseract も同梱されるため、
別途の導入は要りません。

### C-1. 利用者の手順

1. `ikensho-ocr-setup-x.y.z.exe` を実行します
2. 画面の指示に従ってインストールします（既定は `C:\Program Files\主治医意見書読み取り`）
3. スタートメニューの「主治医意見書 読み取り」を起動すると、
   ローカルサーバが立ち上がり既定のブラウザで画面が開きます

コマンドラインからも使えます（インストール時に PATH へ追加した場合）。

```
ikensho extract "C:\scans\*.pdf" --csv C:\scans\out.csv
```

### C-2. インストーラの作り方（配布側）

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
| Windows | 「アプリと機能」から「主治医意見書 読み取り」を削除 |

読み取り結果はブラウザ版では端末内（localStorage）に保存されます。
消す場合は画面の「保存・出力」から各件を削除するか、ブラウザのサイトデータを削除してください。
