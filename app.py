"""
Word → PDF 変換サーバー（Render用）
LibreOffice を使って .docx ファイルを PDF に変換します。
"""

import os
import tempfile
import urllib.parse
from pathlib import Path
from flask import Flask, request, Response, send_file
import subprocess
import shutil

app = Flask(__name__, static_folder=".", static_url_path="")

def find_soffice():
    for cmd in ("soffice", "libreoffice"):
        if shutil.which(cmd):
            return cmd
    return None

@app.route("/")
def index():
    return app.send_static_file("tool.html")

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
            [soffice, "--headless", "--convert-to", "pdf", input_path, "--outdir", tmpdir],
            capture_output=True, text=True, timeout=60
        )

        if result.returncode != 0 or not os.path.exists(pdf_path):
            return {"error": f"変換失敗: {result.stderr}"}, 500

        out_name = Path(filename).stem + ".pdf" if filename else "converted.pdf"
        encoded_name = urllib.parse.quote(out_name)

        return send_file(
            pdf_path,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=out_name
        )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8765))
    app.run(host="0.0.0.0", port=port)
