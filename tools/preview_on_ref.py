# -*- coding: utf-8 -*-
"""テンプレート座標を、その様式の参照画像に重ねて検証用PNGを出力する。"""
import json, os, sys
import cv2

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def main(tpl_id, out_prefix):
    tpl = json.load(open(os.path.join(ROOT, "templates", f"{tpl_id}.json"), encoding="utf-8"))
    for p in tpl["pages"]:
        ref = cv2.imread(os.path.join(ROOT, "templates", "refs", p["ref"]), cv2.IMREAD_GRAYSCALE)
        vis = cv2.cvtColor(ref, cv2.COLOR_GRAY2BGR)
        H, W = ref.shape
        for b in p["boxes"]:
            x, y, w, h = b["rect"]
            cv2.rectangle(vis, (int(x*W), int(y*H)), (int((x+w)*W), int((y+h)*H)), (0, 0, 255), 1)
        for t in p["texts"]:
            x, y, w, h = t["rect"]
            col = (0, 160, 0) if t["type"] == "circle" else (255, 0, 0)
            cv2.rectangle(vis, (int(x*W), int(y*H)), (int((x+w)*W), int((y+h)*H)), col, 1)
        out = f"{out_prefix}_p{p['index']}.png"
        cv2.imwrite(out, vis)
        print("wrote", out, f"boxes={len(p['boxes'])} texts={len(p['texts'])}")

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
