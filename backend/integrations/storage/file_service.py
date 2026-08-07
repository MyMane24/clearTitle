"""Service for reading OCR output files and listing output directories.

Extracted verbatim from `backend/services/file_service.py`.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from backend.integrations.storage.file_utils import BASE_DIR, read_json

SAFE_ID = re.compile(r"^[A-Za-z0-9_-]+$")


def _valid_id(value: str) -> bool:
    return bool(SAFE_ID.fullmatch(value))


def get_case_ocr_raw(case_id: str, doc_id: str) -> dict | None:
    """Return the merged OCR JSON for a document, or None if not found."""
    if not _valid_id(case_id) or not _valid_id(doc_id):
        return None
    case_dir = BASE_DIR / "outputs" / case_id
    merged_path = case_dir / "ocr_raw" / f"{doc_id}_merged.json"
    if not merged_path.exists():
        return None
    return read_json(merged_path)


def list_output_cases() -> list[dict]:
    """Return case-like records discovered from outputs/* folders."""
    outputs_dir = BASE_DIR / "outputs"
    if not outputs_dir.exists():
        return []

    # Top-level storage base directories that are not cases
    skip = {"raw_ocr", "structured"}

    cases = []
    for case_dir in sorted(outputs_dir.iterdir()):
        if not case_dir.is_dir() or not _valid_id(case_dir.name):
            continue
        if case_dir.name in skip:
            continue
        ocr_files = sorted((case_dir / "ocr_raw").glob("*_merged.json"))
        structured_files = sorted((case_dir / "structured").glob("*.json"))
        total_docs = max(len(ocr_files), len(structured_files))
        try:
            updated_ts = case_dir.stat().st_mtime
            updated_at = datetime.fromtimestamp(updated_ts, tz=timezone.utc).isoformat()
        except OSError:
            updated_ts = 0
            updated_at = ""
        cases.append({
            "id": case_dir.name,
            "status": "outputs",
            "total_docs": total_docs,
            "completed_docs": len(structured_files) or len(ocr_files),
            "failed_docs": 0,
            "created_at": updated_at,
            "updated_at": updated_at,
            "source": "outputs",
            "sort_ts": updated_ts,
        })
    cases.sort(key=lambda case: case.get("sort_ts", 0), reverse=True)
    for c in cases:
        c.pop("sort_ts", None)
    return cases


def get_case_bundle_from_filesystem(case_id: str) -> list[dict] | None:
    """Read structured result files from outputs/{case_id}/structured/
    as a fallback when MySQL has no records."""
    if not _valid_id(case_id):
        return None
    structured_dir = BASE_DIR / "outputs" / case_id / "structured"
    if not structured_dir.exists():
        return None
    pattern = re.compile(r"^(DOC_\d+)_(.+)\.json$")
    docs = []
    for path in sorted(structured_dir.glob("*.json")):
        m = pattern.match(path.name)
        if not m:
            continue
        doc_id = m.group(1)
        doc_type = m.group(2)
        try:
            data = read_json(path)
        except (OSError, TypeError, ValueError):
            continue
        docs.append({
            "doc_id": doc_id,
            "doc_index": int(doc_id.split("_")[1]),
            "filename": path.name,
            "document_type": doc_type,
            "structured_json": data,
        })
    return docs if docs else None


def list_case_ocr_raw(case_id: str) -> list[dict]:
    """Return merged OCR files available for a case."""
    if not _valid_id(case_id):
        return []
    ocr_dir = BASE_DIR / "outputs" / case_id / "ocr_raw"
    if not ocr_dir.exists():
        return []

    docs = []
    for path in sorted(ocr_dir.glob("*_merged.json")):
        doc_id = path.name.removesuffix("_merged.json")
        if not _valid_id(doc_id):
            continue
        item = {
            "doc_id": doc_id,
            "filename": path.name,
            "rel": f"ocr_raw/{path.name}",
            "size_kb": round(path.stat().st_size / 1024, 1),
        }
        try:
            raw = read_json(path)
            if isinstance(raw, dict) and raw.get("total_pages") is not None:
                item["total_pages"] = raw["total_pages"]
        except (OSError, TypeError, ValueError):
            pass
        docs.append(item)
    return docs


def list_case_outputs(case_id: str) -> list[dict]:
    """Return a nested listing of the case output directory."""
    if not _valid_id(case_id):
        return []
    case_dir = BASE_DIR / "outputs" / case_id
    if not case_dir.exists():
        return []

    def _walk(parent: Path, rel_prefix: str = "") -> list[dict]:
        entries = []
        for child in sorted(parent.iterdir()):
            rel = f"{rel_prefix}/{child.name}" if rel_prefix else child.name
            if child.is_file():
                entries.append({
                    "name": child.name,
                    "type": "file",
                    "size_kb": round(child.stat().st_size / 1024, 1),
                    "rel": rel,
                })
            elif child.is_dir():
                entries.append({
                    "name": child.name,
                    "type": "dir",
                    "rel": rel,
                    "children": _walk(child, rel),
                })
        return entries

    return _walk(case_dir)
