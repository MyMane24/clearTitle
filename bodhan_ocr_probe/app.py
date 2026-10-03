"""Bodhan AI Indic-OCR probe — upload window.

Run:  venv\\Scripts\\python.exe bodhan_ocr_probe\\app.py
Open: http://127.0.0.1:8125
Upload a PDF, pick table format / max_tokens, then verify the OCR text
page-by-page against the rendered original document.
"""
import base64
import sys
from pathlib import Path

import fitz
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import HTMLResponse

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
from bodhan import run_digitize  # noqa: E402

HERE = _HERE
app = FastAPI()

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Bodhan OCR probe</title>
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
#status{color:#2563eb;font-size:14px;margin-bottom:1rem}
</style></head><body>
<h2>Bodhan AI &mdash; Indic-OCR probe</h2>
<form method="post" enctype="multipart/form-data" action="/run" onsubmit="startStatus()">
<div class="grid">
<input type="file" name="file" accept=".pdf,.png,.jpg,.jpeg">
<select name="table_format">
<option value="html" selected>table: html</option><option value="markdown">table: markdown</option>
</select>
<input type="number" name="max_tokens" value="4096" min="1024" step="1024" title="per-block token limit">
<button type="submit">Run OCR</button>
</div>
</form>
<div id="status"></div>
<div id="out">__OUT__</div>
<script>
function startStatus(){
  var t0=Date.now(), s=document.getElementById('status');
  s.textContent='Processing\\u2026';
  setInterval(function(){ s.textContent='Processing\\u2026 '+(Math.round((Date.now()-t0)/1000))+'s'; },1000);
}
</script>
</body></html>"""


def _page_images(path: Path, dpi: int = 150) -> list:
    if path.suffix.lower() in {".png", ".jpg", ".jpeg"}:
        mime = "image/jpeg" if path.suffix.lower() == ".jpg" else "image/png"
        return ["data:%s;base64,%s" % (mime, base64.b64encode(path.read_bytes()).decode())]
    out = []
    doc = fitz.open(str(path))
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    for page in doc:
        pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)
        out.append("data:image/png;base64," + base64.b64encode(pix.tobytes("png")).decode())
    doc.close()
    return out


def _render_result(filename: str, res: dict) -> str:
    if res.get("error"):
        return ("<h3>Error (%s, HTTP %s)</h3><pre>%s</pre>"
                % (res.get("stage"), res.get("http_status"),
                   _esc(str(res.get("body", res)))))

    pages = res.get("pages") or []
    meta = ("<div class='meta'>pages %d &middot; usage %s &middot; table_format %s</div>"
            % (len(pages), res.get("usage"), res.get("table_format")))

    imgs = _page_images(HERE / "files" / filename)
    cards = []
    for i, img in enumerate(imgs):
        pr = pages[i] if i < len(pages) else None
        if pr is None:
            p = "(no OCR text for this page)"
        elif pr.get("error"):
            p = "Error: HTTP %s\n%s" % (pr["error"].get("http_status"), pr["error"].get("body"))
        else:
            p = pr.get("text") or ""
        blocks = pr.get("blocks") if pr else None
        detail = ("<details><summary>Blocks JSON</summary><pre>%s</pre></details>"
                  % _esc(_pp(blocks))) if blocks else ""
        cards.append(
            "<div class='card'><h4>Page %d &mdash; original vs OCR</h4>"
            "<div class='cols'><div class='img'><img src='%s'></div>"
            "<div class='txt'><pre>%s</pre></div></div>%s</div>"
            % (i + 1, img, _esc(p), detail))
    body = "".join(cards) if cards else "<p>No pages returned.</p>"
    return f"<h3>{_esc(filename)}</h3>{meta}{body}"


def _esc(s) -> str:
    return str(s).replace("<", "&lt;")


def _pp(obj) -> str:
    import json
    return json.dumps(obj, indent=2, ensure_ascii=False, default=str)


@app.get("/", response_class=HTMLResponse)
def index():
    return PAGE.replace("__OUT__", "")


@app.post("/run", response_class=HTMLResponse)
def run(file: UploadFile = File(...), table_format: str = Form("html"),
        max_tokens: int = Form(4096)):
    src = HERE / "files" / Path(file.filename).name
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(file.file.read())
    out = run_digitize(src, table_format=table_format, max_tokens=max_tokens)
    return PAGE.replace("__OUT__", _render_result(file.filename, out))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8125)