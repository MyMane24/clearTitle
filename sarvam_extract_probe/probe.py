"""CLI probe: `python probe.py <doc.pdf> [DOC_TYPE]` -> prints Extract JSON."""
import io
import json
import sys
from pathlib import Path

if isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from extract import run_extract
from schema_bridge import DOC_TYPES, to_sarvam_schema


def _die(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def main():
    args = sys.argv[1:]
    if len(args) < 1:
        _die("usage: python probe.py <doc.pdf> [DOC_TYPE]")
    doc = Path(args[0])
    if not doc.exists():
        _die(f"not found: {doc}")

    doc_type = args[1] if len(args) > 1 else "ENCUMBRANCE_CERTIFICATE"
    if doc_type not in DOC_TYPES:
        _die(f"unknown doc_type {doc_type!r}; available: {', '.join(DOC_TYPES)}")

    schema = to_sarvam_schema(doc_type)
    print(f"-> extract {doc.name} as {doc_type}")
    out = run_extract(doc, schema)
    if out.get("error"):
        print(json.dumps(out, indent=2, ensure_ascii=False), file=sys.stderr)
        _die(f"extract failed at stage {out.get('stage')}")
    print(json.dumps(out, indent=2, ensure_ascii=False))

    save_dir = Path(__file__).parent / "results"
    save_dir.mkdir(parents=True, exist_ok=True)
    save = save_dir / f"{doc.stem}_{doc_type}.json"
    save.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n-> saved {save}")


if __name__ == "__main__":
    main()