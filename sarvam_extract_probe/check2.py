import json
import sys
sys.path.insert(0, r"C:\Users\Asus\OneDrive\Desktop\clearTitle")
sys.path.insert(0, r"C:\Users\Asus\OneDrive\Desktop\clearTitle\sarvam_extract_probe")
from schema_bridge import DOC_TYPES, to_sarvam_schema

def depth(obj):
    if not isinstance(obj, dict):
        return 0
    if "properties" not in obj:
        return 0
    return 1 + max((depth(v) for v in obj["properties"].values()), default=0)

for dt in DOC_TYPES:
    s = to_sarvam_schema(dt)
    print(f"{dt}: object_depth={depth(s)}, keys={list(s['properties'].keys())[:5]}...")

print()
# show flattened EC example top keys
ec = to_sarvam_schema("ENCUMBRANCE_CERTIFICATE")
print("EC top keys:", list(ec['properties'].keys()))
for k, v in ec['properties'].items():
    child_depth = depth(v)
    if child_depth:
        print(f"  {k}: depth={child_depth}")
print()
# show flattened sale deed
sd = to_sarvam_schema("SALE_DEED")
print("SD top keys:", list(sd['properties'].keys()))
for k, v in sd['properties'].items():
    child_depth = depth(v)
    if child_depth:
        print(f"  {k}: depth={child_depth}")