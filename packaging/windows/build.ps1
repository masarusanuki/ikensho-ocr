# 主治医意見書 読み取り — Windows インストーラのビルド
#
#   前提: Python 3.11 以上 / Inno Setup 6 / インターネット接続
#   使い方: packaging\windows で  .\build.ps1
#
# 出来上がるもの: dist\ikensho-ocr-setup-<version>.exe
#   Python も日本語OCRも同梱するため、利用者側の別途インストールは不要。
#   **GPU は要りません。** 認識は onnxruntime の CPU 版で動きます。

$ErrorActionPreference = 'Stop'

# **外部コマンドの失敗で止める。** PowerShell は pip が失敗しても素通りするので、
# 以前これで「本体が入っていない exe」が出来かけた
function Invoke-Checked {
    param([string]$What, [scriptblock]$Body)
    & $Body
    if ($LASTEXITCODE -ne 0) { throw "$What に失敗しました（終了コード $LASTEXITCODE）" }
}

# Python 側の出力が日本語で、コンソールが cp932 だと落ちる
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'

$root = (Resolve-Path "$PSScriptRoot\..\..").Path
$work = "$PSScriptRoot\build"
$dist = "$PSScriptRoot\dist"
$tessVersion = '5.3.3.20231005'
$tessUrl = "https://digi.bib.uni-mannheim.de/tesseract/tesseract-ocr-w64-setup-$tessVersion.exe"

Write-Host '== 作業ディレクトリを準備 =='
New-Item -ItemType Directory -Force -Path $work, $dist | Out-Null

Write-Host '== Python 依存関係を導入 =='
python -m venv "$work\venv"
Invoke-Checked 'pip の更新' {
    & "$work\venv\Scripts\python.exe" -m pip install --upgrade pip wheel
}
# [ocr] を付けないと日本語の認識モデルが動かない（既定エンジンが使えなくなる）。
# rapidocr-onnxruntime が入れる onnxruntime は CPU 版なので GPU は要らない
Invoke-Checked '本体の導入' {
    & "$work\venv\Scripts\python.exe" -m pip install "$root\python[ocr]"
}
Invoke-Checked 'pyinstaller の導入' {
    & "$work\venv\Scripts\python.exe" -m pip install pyinstaller
}

Write-Host '== 日本語の認識モデルを取得 =='
# 実測でいちばん良かった japan_v4（PP-OCRv4 日本語専用・14MB）。
# これが無いと中国語向けの既定モデルになり、文字正解率が 78.0% → 66.7% に落ちる
Invoke-Checked '認識モデルの取得' {
    & "$work\venv\Scripts\python.exe" "$root\tools\fetch_ocr_model.py" japan_v4
}

Write-Host '== 配信用のWebファイルを生成 =='
Invoke-Checked 'Webファイルの生成' {
    & "$work\venv\Scripts\python.exe" "$root\tools\build_web.py"
}

Write-Host '== tesseract を取得 =='
# 公式インストーラから中身だけ取り出す（7-Zip が必要）
$tessExe = "$work\tesseract-setup.exe"
if (-not (Test-Path $tessExe)) {
    Invoke-WebRequest -Uri $tessUrl -OutFile $tessExe
}
$tessDir = "$work\tesseract"
if (-not (Test-Path $tessDir)) {
    & 7z x $tessExe "-o$tessDir" -y | Out-Null
}
# 日本語データが無ければ取得する
$tessdata = "$tessDir\tessdata"
New-Item -ItemType Directory -Force -Path $tessdata | Out-Null
foreach ($lang in @('jpn', 'eng')) {
    $f = "$tessdata\$lang.traineddata"
    if (-not (Test-Path $f)) {
        Invoke-WebRequest -OutFile $f `
            -Uri "https://github.com/tesseract-ocr/tessdata/raw/main/$lang.traineddata"
    }
}

Write-Host '== 実行ファイルを作成 =='
# モデルが無いまま進むと、認識できない exe が出来上がる
if (-not (Test-Path "$root\models\ocr\japan_v4")) {
    throw "日本語の認識モデルがありません: $root\models\ocr\japan_v4"
}
Push-Location $work
& "$work\venv\Scripts\pyinstaller.exe" `
    --noconfirm --clean --name ikensho `
    --add-data "$root\schema;schema" `
    --add-data "$root\templates;templates" `
    --add-data "$root\dict;dict" `
    --add-data "$root\models\ocr;models\ocr" `
    --add-data "$root\dist\web;dist\web" `
    --add-data "$root\README.md;." `
    --add-data "$root\DEVNOTES.md;." `
    --add-data "$tessDir;tesseract" `
    --collect-all pypdfium2 `
    --collect-all cv2 `
    --collect-all rapidocr_onnxruntime `
    --collect-all onnxruntime `
    "$PSScriptRoot\launcher.py"
$code = $LASTEXITCODE
Pop-Location
if ($code -ne 0) { throw "pyinstaller に失敗しました（終了コード $code）" }

Write-Host '== インストーラを作成 =='
$version = (& "$work\venv\Scripts\python.exe" -c "import ikensho_ocr;print(ikensho_ocr.__version__)").Trim()
Invoke-Checked 'インストーラの作成' {
    & 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe' `
        "/DMyAppVersion=$version" "/DMySourceDir=$work\dist\ikensho" "/DMyOutputDir=$dist" `
        "$PSScriptRoot\ikensho.iss"
}

Write-Host ''
Write-Host "完成: $dist\ikensho-ocr-setup-$version.exe"
