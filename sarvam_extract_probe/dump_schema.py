import json, sys
sys.path.insert(0, r"C:\Users\Asus\OneDrive\Desktop\clearTitle")
sys.path.insert(0, r"C:\Users\Asus\OneDrive\Desktop\clearTitle\sarvam_extract_probe")
from schema_bridge import to_sarvam_schema
s = to_sarvam_schema("ENCUMBRANCE_CERTIFICATE")
print(json.dumps(s, indent=1))
# report any property without a non-empty description
def walk(x, path):
    if isinstance(x, dict):
        if "description" in x and not str(x["description"]).strip():
            print("EMPTY DESC:", path, x)
        for k, v in x.items():
            walk(v, f"{path}.{k}")
    elif isinstance(x, list):
        for i, v in enumerate(x):
            walk(v, f"{path}[{i}]")
walk(s, "root")