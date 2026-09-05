# 主治医意見書 読み取り（Python版）
#   docker build -t ikensho-ocr -f packaging/Dockerfile .
#   docker run --rm -p 8765:8765 ikensho-ocr serve --host 0.0.0.0
#   docker run --rm -v "$PWD/scans:/data" ikensho-ocr extract '/data/*.pdf' --csv /data/out.csv
FROM python:3.12-slim

# 日本語OCR（tesseract）と PDF 描画に必要なもの
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr tesseract-ocr-jpn \
        libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY python/ /app/python/
COPY schema/ /app/schema/
COPY templates/ /app/templates/
COPY dict/ /app/dict/
COPY web/ /app/web/
COPY tools/ /app/tools/
COPY README.md DEVNOTES.md /app/

RUN pip install --no-cache-dir -e /app/python \
    && python /app/tools/build_web.py

EXPOSE 8765
ENTRYPOINT ["ikensho"]
CMD ["serve", "--host", "0.0.0.0", "--no-browser"]
