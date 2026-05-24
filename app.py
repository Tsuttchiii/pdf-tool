"""
Word → PDF 変換サーバー（Render用）
LibreOffice を使って .docx ファイルを PDF に変換します。
"""

from PIL import Image
from pillow_heif import register_heif_opener
register_heif_opener()

import cv2
import numpy as np

import os
import tempfile
import urllib.parse
import subprocess
import shutil

from pathlib import Path
from flask import Flask, request, Response, send_file

# HEIC対応
register_heif_opener()

app = Flask(__name__, static_folder=".", static_url_path="")

# LibreOffice探索
def find_soffice():
    for cmd in ("soffice", "libreoffice"):
        if shutil.which(cmd):
            return cmd
    return None


# =========================
# ホーム
# =========================

@app.route("/")
def index():
    return app.send_static_file("tool.html")


# =========================
# Word → PDF
# =========================

@app.route("/convert", methods=["POST", "OPTIONS"])
def convert():

    if request.method == "OPTIONS":
        res = Response()
        res.headers["Access-Control-Allow-Origin"] = "*"
        res.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        res.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return res

    soffice = find_soffice()

    if not soffice:
        return {"error": "LibreOfficeが見つかりません"}, 500

    if "file" not in request.files:
        return {"error": "ファイルが見つかりません"}, 400

    file = request.files["file"]
    filename = file.filename

    with tempfile.TemporaryDirectory() as tmpdir:

        input_path = os.path.join(tmpdir, "input.docx")
        pdf_path = os.path.join(tmpdir, "input.pdf")

        file.save(input_path)

        result = subprocess.run(
            [
                soffice,
                "--headless",
                "--convert-to",
                "pdf",
                input_path,
                "--outdir",
                tmpdir
            ],
            capture_output=True,
            text=True,
            timeout=60
        )

        if result.returncode != 0 or not os.path.exists(pdf_path):
            return {
                "error": f"変換失敗: {result.stderr}"
            }, 500

        out_name = (
            Path(filename).stem + ".pdf"
            if filename
            else "converted.pdf"
        )

        encoded_name = urllib.parse.quote(out_name)

        return send_file(
            pdf_path,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=out_name
        )


# =========================
# SCAN ENHANCE
# =========================
def read_image(path):
    pil_img = Image.open(path).convert("RGB")
    img = np.array(pil_img)
    return cv2.cvtColor(img, cv2.COLOR_RGB2BGR)

@app.route("/scan", methods=["POST"])
def scan_image():

    if "file" not in request.files:
        return {"error": "画像がありません"}, 400

    file = request.files["file"]

    # 元の拡張子を保持して保存
    ext = os.path.splitext(file.filename)[1] if file.filename else ".jpg"
    
    with tempfile.TemporaryDirectory() as tmpdir:

        input_path  = os.path.join(tmpdir, "input" + ext)  # ★ 拡張子を維持
        output_path = os.path.join(tmpdir, "output.jpg")
        file.save(input_path)

    try:
        img = read_image(input_path)
    except Exception as e:
        return {"error": f"画像を読み込めませんでした: {e}"}, 400

        # ★ imread 失敗チェック
        if img is None:
            return {"error": f"画像を読み込めませんでした（形式: {ext}）"}, 400

        gray     = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        denoised = cv2.fastNlMeansDenoising(gray, h=10)
        clahe    = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(denoised)

        th = cv2.adaptiveThreshold(
            enhanced, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            blockSize=31,
            C=15
        )

        kernel  = np.ones((2, 2), np.uint8)
        cleaned = cv2.morphologyEx(th, cv2.MORPH_CLOSE, kernel)

        cv2.imwrite(output_path, cleaned, [cv2.IMWRITE_JPEG_QUALITY, 95])

        return send_file(
            output_path,
            mimetype="image/jpeg",
            as_attachment=True,
            download_name="scanned.jpg"
        )
