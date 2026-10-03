import sys
sys.path.insert(0, r"C:\Users\Asus\OneDrive\Desktop\clearTitle")
sys.path.insert(0, r"C:\Users\Asus\OneDrive\Desktop\clearTitle\sarvam_extract_probe")
from schema_bridge import DOC_TYPES, to_sarvam_schema

bad = []
def walk(x, path):
    if isinstance(x, dict):
        if path and ("description" not in x or not str(x.get("description", "")).strip()):
            bad.append((path, list(x.keys())))
        for k, v in x.items():
            walk(v, f"{path}.{k}")
    elif isinstance(x, list):
        for i, v in enumerate(x):
            walk(v, f"{path}[{i}]")

for dt in DOC_TYPES:
    walk(to_sarvam_schema(dt), "")
print("fields missing description:", bad if bad else "none")