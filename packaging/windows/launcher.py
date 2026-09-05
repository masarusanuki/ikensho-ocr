# -*- coding: utf-8 -*-
"""Windows 版の起動口。

ローカルサーバを立ち上げ、既定のブラウザで確認・編集画面を開く。
同梱した tesseract を使えるよう、実行時に環境変数を整える。
"""
import os
import sys


def _setup_bundled_tesseract():
    """インストーラで同梱した tesseract を PATH に通す。"""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.argv[0])))
    tess_dir = os.path.join(base, "tesseract")
    if os.path.isdir(tess_dir):
        os.environ["PATH"] = tess_dir + os.pathsep + os.environ.get("PATH", "")
        tessdata = os.path.join(tess_dir, "tessdata")
        if os.path.isdir(tessdata):
            os.environ["TESSDATA_PREFIX"] = tessdata


def main():
    _setup_bundled_tesseract()
    from ikensho_ocr.cli import main as cli_main
    argv = sys.argv[1:]
    if not argv:
        argv = ["serve"]          # ダブルクリック起動時は画面を開く
    cli_main(argv)


if __name__ == "__main__":
    main()
