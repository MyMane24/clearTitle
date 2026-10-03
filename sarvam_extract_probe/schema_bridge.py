"""Convert the project's LLM extraction templates (static.py) into Sarvam Doc-AI Extract schemas.

Sarvam's rule: "schema nesting may not exceed 4 levels" — and it counts every
property/items node as a level. Deep LLM templates (EC ledger -> parties -> vendors)
can't survive nested. So each top-level section becomes an object whose leaf fields
are flattened to dotted keys carrying the full original path:

    historical_ledger.execution_date, historical_ledger.parties.vendors, ...

Field names match the Groq/Gemini schema exactly; only the nesting is flattened.
Arrays of scalars stay arrays; arrays of objects become parallel arrays per leaf.
"""
import re
import sys
from copy import deepcopy
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))  # repo root, for backend import

from backend.services.schemas import SCHEMA_MAP, _generic_schema  # noqa: E402

MAX_LEVEL = 4  # Sarvam hard cap, counts properties + array-items nodes


def _humanize(key: str) -> str:
    return re.sub(r"_+", " ", key).strip().capitalize()


def _scalar(value, desc: str) -> dict:
    if isinstance(value, bool):
        return {"type": "boolean", "description": desc}
    if isinstance(value, int):
        return {"type": "integer", "description": desc}
    if isinstance(value, float):
        return {"type": "number", "description": desc}
    return {"type": "string", "description": desc}


def _flat_leaves(node, prefix: str, out: list) -> None:
    """Collect (dotted_key, template_value) leaves, one per scalar array/field."""
    if isinstance(node, dict):
        for k, v in node.items():
            _flat_leaves(v, f"{prefix}{k}.", out)
    elif isinstance(node, list) and node and isinstance(node[0], dict):
        for inner_k in node[0].keys():
            _flat_leaves(node[0][inner_k], f"{prefix}{inner_k}.", out)
    elif isinstance(node, list):
        name = _humanize(prefix.rstrip("."))
        items = _scalar(node[0], "Item") if node else {"type": "string", "description": "Item"}
        out.append((prefix.rstrip("."), {"type": "array", "description": name, "items": items}))
    else:
        out.append((prefix.rstrip("."), None))


def to_sarvam_schema(doc_type: str) -> dict:
    template = deepcopy(SCHEMA_MAP.get(doc_type, _generic_schema(doc_type)))
    root_props = {}
    for section, value in template.items():
        if isinstance(value, dict):
            leaves = []
            _flat_leaves(value, "", leaves)
            root_props[section] = {
                "type": "object",
                "description": _humanize(section),
                "properties": {
                    k: (_scalar(v, _humanize(k)) if v is None else v)
                    for k, v in leaves
                },
            }
        elif isinstance(value, list):
            if value and isinstance(value[0], dict):
                root_props[section] = {"type": "array", "description": _humanize(section),
                                       "items": _props_flat(value[0])}
            else:
                root_props[section] = {"type": "array", "description": _humanize(section),
                                       "items": _scalar(value[0], "Item") if value else {"type": "string", "description": "Item"}}
        else:
            root_props[section] = _scalar(value, _humanize(section))
    return {"type": "object", "properties": root_props}


def _props_flat(obj: dict) -> dict:
    """Single-level object properties for a list-of-dicts element."""
    leaves = []
    _flat_leaves(obj, "", leaves)
    return {"type": "object", "description": "Item",
            "properties": {k: (_scalar(v, _humanize(k)) if v is None else v) for k, v in leaves}}


DOC_TYPES = sorted(SCHEMA_MAP.keys())


if __name__ == "__main__":
    import json
    for dt in DOC_TYPES + ["UNKNOWN_TYPE"]:
        print(dt, json.dumps(to_sarvam_schema(dt))[:160].replace("\n", " "))