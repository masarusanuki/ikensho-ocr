# 主治医意見書 読み取り
#
# Windows / macOS / Linux のどれでも、Docker があればこれだけで動きます。
# Python も tesseract（日本語OCR）も同梱するので、別途の導入は要りません。
#
#   docker compose -f packaging/docker-compose.yml up
#   → ブラウザで http://localhost:8765 を開く
#
# または
#   docker build -t ikensho-ocr -f packaging/Dockerfile .
#   docker run --rm -p 8765:8765 ikensho-ocr
#
# 大量のファイルをコマンドで処理する場合
#   docker run --rm -v "$PWD/scans:/data" ikensho-ocr \
#       extract '/data/*.pdf' --csv /data/out.csv
FROM python:3.12-slim

# 日本語OCR（tesseract）と、PDF描画・画像処理に必要なもの
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr tesseract-ocr-jpn \
        libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 依存関係だけ先に入れて、キャッシュを効かせる
COPY python/pyproject.toml /app/python/
COPY python/ikensho_ocr/__init__.py /app/python/ikensho_ocr/
RUN pip install --no-cache-dir -e /app/python

COPY python/ /app/python/
COPY schema/ /app/schema/
COPY templates/ /app/templates/
COPY dict/ /app/dict/
COPY web/ /app/web/
COPY tools/ /app/tools/
COPY docs/ /app/docs/
COPY README.md DEVNOTES.md /app/

# 確認・編集画面を組み立てる
RUN python /app/tools/build_web.py

# LLM による候補提示を使う場合は、GGUFモデルを /app/models に置く
#   docker run -v /path/to/models:/app/models ...
VOLUME ["/data", "/app/models"]

EXPOSE 8765
ENTRYPOINT ["ikensho"]
CMD ["serve", "--host", "0.0.0.0", "--no-browser"]
