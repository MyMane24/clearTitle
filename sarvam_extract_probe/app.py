"""Sarvam Extract upload window.

Run:  venv\\Scripts\\python.exe sarvam_extract_probe\\app.py
Open: http://127.0.0.1:8123
Upload one PDF, pick doc type, see the Extract JSON (no digitise, no LLM credits).
"""
import json
import sys
from pathlib import Path

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from extract import run_extract  # noqa: E402
from schema_bridge import DOC_TYPES, to_sarvam_schema  # noqa: E402

app = FastAPI()

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Sarvam Extract probe</title>
<style>
body{font-family:Segoe UI,Arial,sans-serif;max-width:900px;margin:2rem auto;padding:0 1rem;color:#111}
select,input{font-size:15px;padding:.4rem .5rem}
pre{background:#f6f7f9;border:1px solid #ddd;padding:1rem;overflow:auto;font-size:13px}
label{margin-right:.6rem}
.grid{display:flex;gap:.6rem;align-items:center;flex-wrap:wrap;margin-bottom:1rem}
button{padding:.5rem 1rem}
</style></head><body>
<h2>Sarvam Doc-AI Extract &mdash; probe</h2>
<form method="post" enctype="multipart/form-data" action="/run">
<div class="grid">
<input type="file" name="file" accept=".pdf">
<select name="doc_type">%s</select>
<select name="language">
<option value="kn-IN" selected>kn-IN</option><option value="en-IN">en-IN</option>
</select>
<button type="submit">Run Extract</button>
</div>
</form>
<div id="out">%s</div>
</body></html>"""

OPTIONS = "".join(f"<option value='{d}'>{d}</option>" for d in DOC_TYPES)


@app.get("/", response_class=HTMLResponse)
def index():
    return PAGE % (OPTIONS, "")


@app.post("/run", response_class=HTMLResponse)
def run(file: UploadFile = File(...), doc_type: str = Form("ENCUMBRANCE_CERTIFICATE"),
        language: str = Form("kn-IN")):
    src = Path("sarvam_extract_probe") / "results" / file.filename
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(file.file.read())

    schema = to_sarvam_schema(doc_type)
    out = run_extract(src, schema, language)
    body = json.dumps(out, indent=2, ensure_ascii=False).replace("<", "&lt;")
    return PAGE % (OPTIONS, f"<h3>{file.filename} as {doc_type}</h3><pre>{body}</pre>")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8123)