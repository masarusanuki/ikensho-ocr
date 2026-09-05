# Windows インストーラのビルド

利用者側は**インストーラを実行するだけ**で使えるようにします。
Python も tesseract（日本語OCR）も同梱するため、別途の導入は要りません。

## 必要なもの（ビルドする側）

| | 入手先 |
|---|---|
| Python 3.11 以上 | https://www.python.org/downloads/windows/ |
| Inno Setup 6 | https://jrsoftware.org/isdl.php |
| 7-Zip（コマンドライン `7z`） | https://www.7-zip.org/ |
| インターネット接続 | tesseract 本体と日本語データの取得に使います |

## 手順

```powershell
cd packaging\windows
.\build.ps1
```

`dist\ikensho-ocr-setup-<version>.exe` ができます。

`build.ps1` は次を自動で行います。

1. 仮想環境を作り、`python/` の本体と依存関係を導入する
2. `tools/build_web.py` で確認・編集画面のファイルを生成する
3. tesseract の公式インストーラを取得し、中身（実行ファイルと `tessdata`）を取り出す
4. 日本語データ `jpn.traineddata` を取得する
5. PyInstaller で1つの実行ファイルにまとめる（様式テンプレート・辞書・Web画面・tesseract を同梱）
6. Inno Setup でインストーラを作る

## GitHub Actions で自動生成する

タグを打つとインストーラがビルドされ、リリースに添付されます。

```bash
git tag v0.1.0
git push origin v0.1.0
```

定義は [.github/workflows/windows-installer.yml](../../.github/workflows/windows-installer.yml) にあります。

## 利用者側の動作

- スタートメニューの「主治医意見書 読み取り」を起動すると、
  ローカルサーバが立ち上がり既定のブラウザで画面が開きます
- インストール時に PATH 追加を選んだ場合は、コマンドプロンプトからも使えます

```
ikensho info
ikensho extract "C:\scans\*.pdf" --csv C:\scans\out.csv
```

## 確認事項

- **同梱ライセンス**: tesseract は Apache-2.0 です。インストーラに含めて再配布できますが、
  ライセンス表記を同梱してください（`LICENSE` と `web/vendor/README.md` に記載）
- **配布サイズ**: 約 250〜350 MB（Python ランタイム・OpenCV・tesseract・日本語データを含む）
- **署名**: 社内配布でも SmartScreen の警告が出ます。必要ならコード署名証明書で署名してください

```powershell
signtool sign /fd SHA256 /a /tr http://timestamp.digicert.com /td SHA256 `
  dist\ikensho-ocr-setup-0.1.0.exe
```
