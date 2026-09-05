# 主治医意見書 読み取り — Windows インストーラのビルド
#
#   前提: Python 3.11 以上 / Inno Setup 6 / インターネット接続
#   使い方: packaging\windows で  .\build.ps1
#
# 出来上がるもの: dist\ikensho-ocr-setup-<version>.exe
#   Python も tesseract も同梱するため、利用者側の別途インストールは不要。

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path "$PSScriptRoot\..\..").Path
$work = "$PSScriptRoot\build"
$dist = "$PSScriptRoot\dist"
$tessVersion = '5.3.3.20231005'
$tessUrl = "https://digi.bib.uni-mannheim.de/tesseract/tesseract-ocr-w64-setup-$tessVersion.exe"

Write-Host '== 作業ディレクトリを準備 =='
New-Item -ItemType Directory -Force -Path $work, $dist | Out-Null

Write-Host '== Python 依存関係を導入 =='
python -m venv "$work\venv"
& "$work\venv\Scripts\python.exe" -m pip install --upgrade pip wheel
& "$work\venv\Scripts\python.exe" -m pip install "$root\python"
& "$work\venv\Scripts\python.exe" -m pip install pyinstaller

Write-Host '== 配信用のWebファイルを生成 =='
& "$work\venv\Scripts\python.exe" "$root\tools\build_web.py"

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
Push-Location $work
& "$work\venv\Scripts\pyinstaller.exe" `
    --noconfirm --clean --name ikensho `
    --add-data "$root\schema;schema" `
    --add-data "$root\templates;templates" `
    --add-data "$root\dict;dict" `
    --add-data "$root\dist\web;dist\web" `
    --add-data "$root\README.md;." `
    --add-data "$root\DEVNOTES.md;." `
    --add-data "$tessDir;tesseract" `
    --collect-all pypdfium2 `
    --collect-all cv2 `
    "$PSScriptRoot\launcher.py"
Pop-Location

Write-Host '== インストーラを作成 =='
$version = (& "$work\venv\Scripts\python.exe" -c "import ikensho_ocr;print(ikensho_ocr.__version__)").Trim()
& 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe' `
    "/DMyAppVersion=$version" "/DMySourceDir=$work\dist\ikensho" "/DMyOutputDir=$dist" `
    "$PSScriptRoot\ikensho.iss"

Write-Host ''
Write-Host "完成: $dist\ikensho-ocr-setup-$version.exe"
