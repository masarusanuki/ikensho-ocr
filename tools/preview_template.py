# -*- coding: utf-8 -*-
"""テンプレート座標を画像に重ねて検証用PNGを出力する。"""
import json, os, sys
import cv2, numpy as np, pypdfium2 as pdfium

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def main(tpl_path, pdf_path, out_prefix, dpi=150):
    tpl = json.load(open(tpl_path, encoding="utf-8"))
    doc = pdfium.PdfDocument(pdf_path)
    for p in tpl["pages"]:
        page = doc[p["index"] - 1]
        img = np.asarray(page.render(scale=dpi / 72.0).to_pil().convert("RGB"))[:, :, ::-1].copy()
        H, W = img.shape[:2]
        for b in p["boxes"]:
            x, y, w, h = b["rect"]
            cv2.rectangle(img, (int(x*W), int(y*H)), (int((x+w)*W), int((y+h)*H)), (0, 0, 255), 1)
        for t in p["texts"]:
            x, y, w, h = t["rect"]
            col = (255, 0, 0) if t["type"] != "circle" else (0, 160, 0)
            cv2.rectangle(img, (int(x*W), int(y*H)), (int((x+w)*W), int((y+h)*H)), col, 2)
        out = f"{out_prefix}_p{p['index']}.png"
        cv2.imwrite(out, img)
        print("wrote", out)

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
