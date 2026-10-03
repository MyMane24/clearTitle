"""Sarvam Vision 2.1 Digitise upload window.

Run:  venv\\Scripts\\python.exe sarvam_digitize_probe\\app.py
Open: http://127.0.0.1:8124
Upload a PDF, pick language / output format / model, then verify the
digitized text page-by-page against the rendered original document.
"""
import base64
import io
import json
from pathlib import Path

import fitz
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import HTMLResponse

import sys
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
from digitise import run_digitise  # noqa: E402

HERE = _HERE
app = FastAPI()

MODELS = ["", "sarvam-vision-2.1", "sarvam-vision", "sarvam-vision-1.5"]

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Sarvam Vision probe</title>
<style>
body{font-family:Segoe UI,Arial,sans-serif;max-width:1100px;margin:2rem auto;padding:0 1rem;color:#111}
select,input{font-size:15px;padding:.4rem .5rem}
pre{background:#f6f7f9;border:1px solid #ddd;padding:1rem;overflow:auto;font-size:13px;white-space:pre-wrap;word-break:break-word}
label{margin-right:.6rem}
.grid{display:flex;gap:.6rem;align-items:center;flex-wrap:wrap;margin-bottom:1rem}
button{padding:.5rem 1rem}
.card{border:1px solid #ddd;border-radius:8px;padding:1rem;margin:1.25rem 0;overflow:hidden}
.card h4{margin:.2rem 0 .8rem}
.cols{display:flex;gap:1rem}
.cols .img{flex:0 0 45%;max-width:45%}
.cols .txt{flex:1 1 55%}
.cols img{max-width:100%;border:1px solid #ddd}
.meta{color:#555;font-size:13px;margin:.3rem 0 1rem}
details{margin-top:.6rem}
summary{cursor:pointer;color:#2563eb}
</style></head><body>
<h2>Sarvam Vision 2.1 &mdash; Digitise probe</h2>
<form method="post" enctype="multipart/form-data" action="/run">
<div class="grid">
<input type="file" name="file" accept=".pdf">
<select name="language">
<option value="kn-IN" selected>kn-IN</option><option value="en-IN">en-IN</option><option value="auto">auto</option>
</select>
<select name="output_format">
<option value="md" selected>md</option><option value="json">json</option><option value="html">html</option>
</select>
<select name="model">%s</select>
<button type="submit">Run Digitise</button>
</div>
</form>
<div id="out">%s</div>
</body></html>"""

MODEL_OPTS = "".join(
    ("<option value='%s'%s>%s</option>" % (m, " selected" if m == "" else "",
                                           m if m else "(server default)")) for m in MODELS)


def _page_images(pdf: Path, dpi: int = 150) -> list:
    out = []
    doc = fitz.open(str(pdf))
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    for page in doc:
        pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)
        out.append("data:image/png;base64," + base64.b64encode(pix.tobytes("png")).decode())
    doc.close()
    return out


def _render_result(filename: str, res: dict) -> str:
    if res.get("error"):
        return f"<h3>Error ({res.get('stage')}, HTTP {res.get('http_status')})</h3><pre>{json.dumps(res, indent=2, ensure_ascii=False, default=str)}</pre>"

    pages = res.get("pages") or []
    meta = f"<div class='meta'>job_id <b>{res.get('job_id')}</b> &middot; status {res.get('final_status')} &middot; usage {json.dumps(res.get('usage'), ensure_ascii=False)}</div>"

    imgs = _page_images(HERE / "results" / filename)
    cards = []
    for i, img in enumerate(imgs):
        p = pages[i]["text"] if i < len(pages) else "(no digitised text for this page)"
        cards.append(
            "<div class='card'><h4>Page %d &mdash; original vs digitised</h4>"
            "<div class='cols'><div class='img'><img src='%s'></div>"
            "<div class='txt'><pre>%s</pre></div></div></div>"
            % (i + 1, img, _esc(p)))
    body = "".join(cards) if cards else "<p>No pages rendered.</p>"

    extras = ""
    if res.get("markdown"):
        extras += f"<details><summary>Full Markdown</summary><pre>{_esc(res['markdown'])}</pre></details>"
    if res.get("payload"):
        extras += f"<details><summary>Raw JSON blocks</summary><pre>{_esc(json.dumps(res['payload'], indent=2, ensure_ascii=False))}</pre></details>"
    return f"<h3>{_esc(filename)}</h3>{meta}{body}{extras}"


def _esc(s: str) -> str:
    return s.replace("<", "&lt;")


@app.get("/", response_class=HTMLResponse)
def index():
    return PAGE % (MODEL_OPTS, "")


@app.post("/run", response_class=HTMLResponse)
def run(file: UploadFile = File(...), language: str = Form("kn-IN"),
        output_format: str = Form("md"), model: str = Form("")):
    src = HERE / "results" / Path(file.filename).name
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(file.file.read())
    out = run_digitise(src, language=language, output_format=output_format, model=model)
    return PAGE % (MODEL_OPTS, _render_result(file.filename, out))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8124)