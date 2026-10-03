import json
import sys
from pathlib import Path
sys.path.insert(0, r"C:\Users\Asus\OneDrive\Desktop\clearTitle")
sys.path.insert(0, r"C:\Users\Asus\OneDrive\Desktop\clearTitle\sarvam_extract_probe")

import fitz
from schema_bridge import DOC_TYPES, to_sarvam_schema

for dt in DOC_TYPES:
    s = to_sarvam_schema(dt)
    depth = 0
    def walk(x, d):
        global depth
        depth = max(depth, d)
        if isinstance(x, dict):
            for k, v in x.items():
                walk(v, d + 1)
        elif isinstance(x, list):
            for v in x:
                walk(v, d + 1)
    walk(s, 0)
    print(f"{dt}: depth={depth}")

print()
for pdf in [r"C:\Users\Asus\OneDrive\Desktop\clearTitle\outputs\998A8755\raw\EC 01-04-2023 to 24-04-2026.pdf",
            r"C:\Users\Asus\OneDrive\Desktop\clearTitle\outputs\998A8755\raw\Sale Deed.pdf"]:
    d = fitz.open(pdf)
    print(f"{Path(pdf).name}: {d.page_count} pages")
    d.close()