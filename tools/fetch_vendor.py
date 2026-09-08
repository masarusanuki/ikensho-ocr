# -*- coding: utf-8 -*-
"""同梱ライブラリを取得しなおす（オフライン動作のため web/vendor/ に置く）。"""
import os
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENDOR = os.path.join(ROOT, "web", "vendor")

ASSETS = [
    ("opencv.js",
     "https://cdn.jsdelivr.net/npm/@techstark/opencv-js@4.10.0-release.1/dist/opencv.js"),
    ("pdf.min.mjs",
     "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.6.82/pdf.min.mjs"),
    ("pdf.worker.min.mjs",
     "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.6.82/pdf.worker.min.mjs"),
    ("tesseract.min.js",
     "https://cdn.jsdelivr.net/npm/tesseract.js@5.1.1/dist/tesseract.min.js"),
    ("tesseract.worker.min.js",
     "https://cdn.jsdelivr.net/npm/tesseract.js@5.1.1/dist/worker.min.js"),
    ("tesseract-core-simd.wasm.js",
     "https://cdn.jsdelivr.net/npm/tesseract.js-core@5.1.1/tesseract-core-simd.wasm.js"),
    ("jpn.traineddata.gz",
     "https://cdn.jsdelivr.net/npm/@tesseract.js-data/jpn@1.0.0/4.0.0_best_int/jpn.traineddata.gz"),
    # onnxruntime-web（日本語のOCRモデルをブラウザで動かすために使う）
    ("ort.wasm.min.js",
     "https://cdn.jsdelivr.net/npm/onnxruntime-web@1.29.0/dist/ort.wasm.min.js"),
    ("ort-wasm-simd-threaded.mjs",
     "https://cdn.jsdelivr.net/npm/onnxruntime-web@1.29.0/dist/ort-wasm-simd-threaded.mjs"),
    ("ort-wasm-simd-threaded.wasm",
     "https://cdn.jsdelivr.net/npm/onnxruntime-web@1.29.0/dist/ort-wasm-simd-threaded.wasm"),
]


def main():
    os.makedirs(VENDOR, exist_ok=True)
    for name, url in ASSETS:
        dst = os.path.join(VENDOR, name)
        print(f"  {name} … ", end="", flush=True)
        with urllib.request.urlopen(url, timeout=300) as r, open(dst, "wb") as fp:
            fp.write(r.read())
        print(f"{os.path.getsize(dst) / 1024 / 1024:.1f} MB")
    print("取得しました。ライセンスは web/vendor/README.md を参照してください。")


if __name__ == "__main__":
    main()
