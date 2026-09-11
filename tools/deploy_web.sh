#!/usr/bin/env bash
# 公開先へビルド成果物だけを置く。
#
# **`.htaccess` / `.htpasswd` / `samples/` は消さない。**
# rsync --delete をそのまま掛けると、配置先にしか無いこれらを消してしまい、
# サイトのパスワードが外れる（実際に外した。その場で直したが、二度とやらないこと）。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${1:-/var/www/html/test-deploy/kaigo_nintei}"

if [ ! -f "$ROOT/dist/web/index.html" ]; then
  echo "先に python3 tools/build_web.py を実行してください。" >&2
  exit 1
fi

echo "置き先: $DEST"
rsync -a --delete \
  --exclude '.htaccess' --exclude '.htpasswd' \
  --exclude 'samples/' --exclude 'ikensho-standalone.html' \
  "$ROOT/dist/web/" "$DEST/"

if [ -f "$ROOT/dist/ikensho-standalone.html" ]; then
  cp "$ROOT/dist/ikensho-standalone.html" "$DEST/ikensho-standalone.html"
  echo "  単一HTML版も置きました"
fi

# パスワードが掛かっているかを必ず確かめる（外れていたら気付けるようにする）
if [ -f "$DEST/.htaccess" ] && [ -f "$DEST/.htpasswd" ]; then
  echo "  パスワード設定: あり"
else
  echo "!! .htaccess / .htpasswd がありません。誰でも見える状態です。" >&2
  echo "   docs/DEVELOPER.md 9.1 の手順で作り直してください。" >&2
  exit 2
fi
echo "完了しました。"
