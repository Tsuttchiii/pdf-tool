"""
Word → PDF 変換サーバー（Render用）
LibreOffice を使って .docx ファイルを PDF に変換します。
"""

from PIL import Image
from pillow_heif import register_heif_opener

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

@app.route("/scan", methods=["POST"])
def scan_image():

    if "file" not in request.files:
        return {"error": "画像がありません"}, 400

    file = request.files["file"]

    with tempfile.TemporaryDirectory() as tmpdir:

        input_path  = os.path.join(tmpdir, "input.jpg")
        output_path = os.path.join(tmpdir, "output.jpg")
        file.save(input_path)

        # ── ① 画像読み込み & グレースケール化 ──────────────────────────
        img  = cv2.imread(input_path)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        #   BGR（カメラの色形式）→ グレー1チャンネルに変換
        #   以降の処理は「明るさ」だけを扱う

        # ── ② ノイズ除去（★追加） ──────────────────────────────────────
        denoised = cv2.fastNlMeansDenoising(gray, h=10)
        #   h=10 : 除去の強さ。大きいほどぼかしが強い（5〜15 が目安）
        #   これをやらないと細かいザラつきが二値化で「汚い点」になる

        # ── ③ コントラスト均一化（★追加） ────────────────────────────
        clahe    = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(denoised)
        #   CLAHE = Contrast Limited Adaptive Histogram Equalization
        #   画像全体ではなく 8×8 の小領域ごとにコントラストを強調
        #   → 照明ムラがあっても「暗い隅」の文字も白黒くっきりになる
        #   clipLimit=2.0 : 強調しすぎを防ぐ上限。大きいと強め

        # ── ④ 適応的二値化（パラメータ改善） ─────────────────────────
        th = cv2.adaptiveThreshold(
            enhanced,
            255,                              # 白の輝度値
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,   # 近傍をガウス重みで平均
            cv2.THRESH_BINARY,                # 明るい→白 暗い→黒
            blockSize=31,                     # ★ 11→31 に変更（重要）
            C=15                              # ★ 2 →15 に変更
        )
        #   blockSize : 「この画素を白か黒か」を決める近傍の大きさ
        #               小さい(11)→細部に敏感→ノイズが出やすい
        #               大きい(31)→大局的に判断→安定して白黒になる
        #   C         : 閾値から引く定数。大きいほど白が増える
        #               文字が飛ぶ場合は下げる、背景が残る場合は上げる

        # ── ⑤ モルフォロジー処理（★追加） ───────────────────────────
        kernel  = np.ones((2, 2), np.uint8)
        cleaned = cv2.morphologyEx(th, cv2.MORPH_CLOSE, kernel)
        #   MORPH_CLOSE = 膨張 → 収縮 の順に適用
        #   文字の小さな「穴」や途切れを埋めて、ゴマ塩ノイズを除去する
        #   kernel(2×2) : 処理する近傍サイズ。大きくすると文字が太る

        # ── ⑥ 保存 ──────────────────────────────────────────────────
        cv2.imwrite(output_path, cleaned, [cv2.IMWRITE_JPEG_QUALITY, 95])
        #   品質 95 で保存（デフォルト 95 より高い → 圧縮劣化を抑える）

        return send_file(
            output_path,
            mimetype="image/jpeg",
            as_attachment=True,
            download_name="scanned.jpg"
        )
