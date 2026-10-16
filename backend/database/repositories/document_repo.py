"""
Document-level persistence operations.

Extracted verbatim from `backend/services/mysql_store.py` (document operations).
"""

from __future__ import annotations

import json
import ntpath
from pathlib import Path
import re
from typing import Any

from backend.database.connection import _get_conn
from backend.shared.ec_ledger import normalize_ec_structured


def init_document(*, case_id: str, doc_id: str, doc_index: int, filename: str, file_paths: dict | None = None, expected_type: str | None = None) -> None:
    with _get_conn() as conn:
        cursor = conn.cursor()
        file_paths_str = json.dumps(file_paths, ensure_ascii=False) if file_paths else None
        cursor.execute(
            "INSERT INTO documents (case_id, doc_id, doc_index, filename, status, file_paths, expected_type) "
            "VALUES (%s, %s, %s, %s, 'uploaded', %s, %s) "
            "ON DUPLICATE KEY UPDATE filename=VALUES(filename), doc_index=VALUES(doc_index), "
            "file_paths=COALESCE(VALUES(file_paths), file_paths), "
            "expected_type=VALUES(expected_type)",
            (case_id, doc_id, doc_index, filename, file_paths_str, expected_type),
        )
        conn.commit()


def update_document_status(
    *,
    case_id: str,
    doc_id: str,
    status: str,
    document_type: str | None = None,
    structured_data: dict | None = None,
    summary: str | None = None,
    merged_ocr_text: str | None = None,
    file_paths: dict | None = None,
    error: str | None = None,
    page_count: int = 0,
    input_tokens: int = 0,
    output_tokens: int = 0,
    latency_ms: int = 0,
    cost_usd: float = 0,
    model_used: str = "",
) -> None:
    with _get_conn() as conn:
        cursor = conn.cursor()
        fields: dict[str, Any] = {"status": status}
        if document_type is not None:
            fields["document_type"] = document_type
        if structured_data is not None:
            fields["structured_data"] = json.dumps(structured_data, ensure_ascii=False)
        if summary is not None:
            fields["summary"] = summary
        if merged_ocr_text is not None:
            fields["merged_ocr_text"] = merged_ocr_text
        if error is not None:
            fields["error"] = error
        if page_count:
            fields["page_count"] = page_count
        if input_tokens:
            fields["input_tokens"] = input_tokens
        if output_tokens:
            fields["output_tokens"] = output_tokens
        if latency_ms:
            fields["latency_ms"] = latency_ms
        if cost_usd:
            fields["cost_usd"] = cost_usd
        if model_used:
            fields["model_used"] = model_used

        set_clause = ", ".join(f"{k} = %s" for k in fields)
        values = [*list(fields.values())]

        # Use MySQL JSON_MERGE_PATCH for atomic file_paths merge (no read-modify-write race)
        if file_paths is not None:
            for key, val in file_paths.items():
                set_clause += ", file_paths = JSON_SET(COALESCE(file_paths, '{}'), %s, %s)"
                values.extend([f"$.{key}", json.dumps(val, ensure_ascii=False) if not isinstance(val, str) else val])

        values.extend([case_id, doc_id])
        cursor.execute(
            f"UPDATE documents SET {set_clause} WHERE case_id = %s AND doc_id = %s",
            values,
        )
        conn.commit()


def get_case_documents(case_id: str) -> list[dict]:
    with _get_conn() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT doc_id, doc_index, filename, document_type, page_count, status, "
            "structured_data AS structured_json, file_paths, input_tokens, output_tokens, "
            "latency_ms, cost_usd, model_used, error, created_at "
            "FROM documents WHERE case_id = %s ORDER BY doc_index ASC",
            (case_id,),
        )
        result = []
        for row in cursor.fetchall():
            doc = dict(row)
            for field in ("structured_json", "file_paths"):
                if doc.get(field) and isinstance(doc[field], str):
                    doc[field] = json.loads(doc[field])
            if isinstance(doc.get("structured_json"), dict):
                doc["structured_json"] = normalize_ec_structured(doc["structured_json"])
            result.append(doc)
        return result


def get_case_bundle(case_id: str) -> list[dict]:
    with _get_conn() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT doc_id, doc_index, filename, document_type, page_count, "
            "structured_data AS structured_json, "
            "input_tokens, output_tokens, latency_ms, cost_usd, model_used "
            "FROM documents WHERE case_id = %s AND status = 'structured' "
            "ORDER BY doc_index ASC",
            (case_id,),
        )
        result = []
        for row in cursor.fetchall():
            doc = dict(row)
            if doc.get("structured_json") and isinstance(doc["structured_json"], str):
                doc["structured_json"] = json.loads(doc["structured_json"])
            if isinstance(doc.get("structured_json"), dict):
                doc["structured_json"] = normalize_ec_structured(doc["structured_json"])
            result.append(doc)
        return result


def increment_retry(*, case_id: str, doc_id: str, error: str) -> None:
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE documents SET retry_count = retry_count + 1, "
            "status = 'failed', error = %s "
            "WHERE case_id = %s AND doc_id = %s",
            (error, case_id, doc_id),
        )
        conn.commit()


def get_failed_documents(case_id: str) -> list[dict]:
    with _get_conn() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT doc_id, doc_index, filename, document_type, error, retry_count "
            "FROM documents WHERE case_id = %s AND status IN ('failed', 'pending_retry') "
            "ORDER BY doc_index ASC",
            (case_id,),
        )
        return [dict(row) for row in cursor.fetchall()]


def replace_document(
    *,
    case_id: str,
    doc_id: str,
    filename: str,
    file_paths: dict,
) -> None:
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE documents SET "
            "filename = %s, "
            "file_paths = %s, "
            "status = 'failed', "
            "retry_count = 0, "
            "error = 'Document replaced — pending retry', "
            "document_type = '', "
            "structured_data = NULL, "
            "summary = NULL, "
            "merged_ocr_text = NULL, "
            "page_count = 0, input_tokens = 0, output_tokens = 0, "
            "latency_ms = 0, cost_usd = 0, model_used = '' "
            "WHERE case_id = %s AND doc_id = %s",
            (filename, json.dumps(file_paths, ensure_ascii=False),
             case_id, doc_id),
        )
        conn.commit()


def skip_document(*, case_id: str, doc_id: str) -> None:
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE documents SET "
            "status = 'skipped', "
            "retry_count = 0, "
            "error = NULL "
            "WHERE case_id = %s AND doc_id = %s",
            (case_id, doc_id),
        )
        conn.commit()


def _legacy_original_filename(
    ordered_files: list[tuple[int, str]],
    *,
    doc_index: int,
    total_docs: int,
    document_type: str,
) -> str | None:
    """Recover a legacy filename only when upload order is unambiguous and corroborated."""
    if len(ordered_files) != total_docs or not 1 <= doc_index <= total_docs:
        return None
    ordered_files = sorted(ordered_files, key=lambda entry: entry[0])
    timestamps = [entry[0] for entry in ordered_files]
    if timestamps and timestamps[-1] - timestamps[0] > 60_000_000_000:
        return None  # unrelated files or a copy operation, not one upload batch

    target_time, filename = ordered_files[doc_index - 1]
    if (doc_index > 1 and ordered_files[doc_index - 2][0] == target_time) or (
        doc_index < total_docs and ordered_files[doc_index][0] == target_time
    ):
        return None  # cannot safely choose between same-time files

    type_terms = set(re.findall(r"[a-z0-9]+", (document_type or "").lower()))
    name_terms = set(re.findall(r"[a-z0-9]+", Path(filename).stem.lower()))
    if len(type_terms & name_terms) < 2:
        return None  # require the filename itself to corroborate the document type
    return filename


def resolve_legacy_pdf_path(case_id: str, doc_id: str) -> Path | None:
    """Resolve an original PDF for placeholder-only records from one intact upload batch."""
    with _get_conn() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT doc_id, doc_index, filename, document_type FROM documents "
            "WHERE case_id = %s ORDER BY doc_index ASC",
            (case_id,),
        )
        rows = cursor.fetchall()

    if not rows or not all(
        re.fullmatch(r"DOC_\d{3}\.pdf", row.get("filename") or "", re.IGNORECASE)
        for row in rows
    ):
        return None
    target = next((row for row in rows if row["doc_id"] == doc_id), None)
    if not target:
        return None

    raw_dir = Path("outputs") / case_id / "raw"
    files = list(raw_dir.glob("*.pdf"))
    if len(files) != len(rows):
        return None
    try:
        ordered = sorted(((path.stat().st_ctime_ns, path) for path in files), key=lambda x: x[0])
    except OSError:
        return None
    times = [item[0] for item in ordered]
    if times[-1] - times[0] > 60_000_000_000:
        return None

    index = int(target.get("doc_index") or 0) - 1
    if not 0 <= index < len(ordered):
        return None
    target_time, path = ordered[index]
    group_start = index
    while group_start > 0 and times[group_start - 1] == target_time:
        group_start -= 1
    group_end = index + 1
    while group_end < len(times) and times[group_end] == target_time:
        group_end += 1
    if group_end - group_start > 1:
        group_files = [ordered[i][1] for i in range(group_start, group_end)]
        group_rows = rows[group_start:group_end]

        def score(filename: str, document_type: str) -> int:
            terms = set(re.findall(r"[a-z0-9]+", Path(filename).stem.lower()))
            type_terms = set(re.findall(r"[a-z0-9]+", (document_type or "").lower()))
            aliases = {
                "ENCUMBRANCE_CERTIFICATE": {"ec"},
                "CONVERSION_ORDER": {"na"},
            }
            type_terms.update(aliases.get(document_type or "", set()))
            return len(terms & type_terms)

        target_row = rows[index]
        target_scores = [score(candidate.name, target_row.get("document_type") or "") for candidate in group_files]
        best = max(target_scores, default=0)
        if best > 0 and target_scores.count(best) == 1:
            path = group_files[target_scores.index(best)]
        else:
            remaining_files = set(range(len(group_files)))
            remaining_rows = [i for i, row in enumerate(group_rows) if row["doc_id"] != doc_id]
            for sibling_idx in remaining_rows:
                sibling_type = group_rows[sibling_idx].get("document_type") or ""
                sibling_scores = {i: score(group_files[i].name, sibling_type) for i in remaining_files}
                sibling_best = max(sibling_scores.values(), default=0)
                winners = [i for i, value in sibling_scores.items() if value == sibling_best and value > 0]
                if len(winners) == 1:
                    remaining_files.remove(winners[0])
            if len(remaining_files) != 1:
                return None
            path = group_files[remaining_files.pop()]
    return path


def get_classification_failed_documents(case_id: str) -> list[dict]:
    with _get_conn() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT doc_id, doc_index, filename, document_type, error, file_paths "
            "FROM documents "
            "WHERE case_id = %s AND status = 'classification_failed' "
            "ORDER BY doc_index ASC",
            (case_id,),
        )
        failed_rows = cursor.fetchall()
        cursor.execute(
            "SELECT doc_index, filename FROM documents WHERE case_id = %s ORDER BY doc_index ASC",
            (case_id,),
        )
        case_rows = cursor.fetchall()

    all_names_are_placeholders = bool(case_rows) and all(
        re.fullmatch(r"DOC_\d{3}\.pdf", row["filename"] or "", re.IGNORECASE)
        for row in case_rows
    )
    raw_dir = Path("outputs") / case_id / "raw"
    raw_files = list(raw_dir.glob("*.pdf")) if all_names_are_placeholders else []
    ordered_files = []
    if len(raw_files) == len(case_rows):
        try:
            ordered_files = [(path.stat().st_ctime_ns, path.name) for path in raw_files]
        except OSError:
            ordered_files = []

    result = []
    for row in failed_rows:
        item = dict(row)
        paths = item.get("file_paths")
        if isinstance(paths, str):
            try:
                paths = json.loads(paths)
            except (TypeError, ValueError):
                paths = {}
        raw_path = paths.get("raw") if isinstance(paths, dict) else None
        if raw_path:
            raw_name = ntpath.basename(str(raw_path).replace("/", "\\"))
            if raw_name:
                item["filename"] = raw_name
        elif ordered_files:
            recovered = _legacy_original_filename(
                ordered_files,
                doc_index=int(item.get("doc_index") or 0),
                total_docs=len(case_rows),
                document_type=item.get("document_type") or "",
            )
            if recovered:
                item["filename"] = recovered
        item.pop("file_paths", None)
        result.append(item)
    return result


def get_document_status(case_id: str, doc_id: str) -> str | None:
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT status FROM documents WHERE case_id = %s AND doc_id = %s",
            (case_id, doc_id),
        )
        row = cursor.fetchone()
        return row[0] if row else None


def get_document_type(case_id: str, doc_id: str) -> str | None:
    """Read the stored document_type for a document (Phase 3: repo-authoritative)."""
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT document_type FROM documents WHERE case_id = %s AND doc_id = %s",
            (case_id, doc_id),
        )
        row = cursor.fetchone()
        return row[0] if row else None


def get_document_resume_state(case_id: str, doc_id: str) -> dict:
    """Return only durable pipeline checkpoint fields needed to resume a retry."""
    with _get_conn() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT document_type, merged_ocr_text, structured_data, file_paths "
            "FROM documents WHERE case_id = %s AND doc_id = %s",
            (case_id, doc_id),
        )
        state = dict(cursor.fetchone() or {})
        if isinstance(state.get("file_paths"), str):
            try:
                state["file_paths"] = json.loads(state["file_paths"])
            except json.JSONDecodeError:
                state["file_paths"] = {}
        return state


def get_document_ocr_text(case_id: str, doc_id: str) -> str | None:
    """Return canonical merged OCR text persisted on the document row."""
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT merged_ocr_text FROM documents WHERE case_id = %s AND doc_id = %s",
            (case_id, doc_id),
        )
        row = cursor.fetchone()
        return row[0] if row else None


def get_document_structured_data(case_id: str, doc_id: str) -> dict | None:
    """Return persisted extraction JSON for a document."""
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT structured_data FROM documents WHERE case_id = %s AND doc_id = %s",
            (case_id, doc_id),
        )
        row = cursor.fetchone()
        if not row or not row[0]:
            return None
        value = json.loads(row[0]) if isinstance(row[0], str) else row[0]
        return value if isinstance(value, dict) else None


def get_expected_type(case_id: str, doc_id: str) -> str | None:
    """Read the slot-declared expected_type (sale_deed/ec) for a document."""
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT expected_type FROM documents WHERE case_id = %s AND doc_id = %s",
            (case_id, doc_id),
        )
        row = cursor.fetchone()
        return row[0] if row else None


def set_document_stage(case_id: str, doc_id: str, stage) -> None:
    status_str = stage.name.lower()
    with _get_conn() as conn:
        cursor = conn.cursor()

        cursor.execute(
            "UPDATE documents SET status = %s WHERE case_id = %s AND doc_id = %s",
            (status_str, case_id, doc_id),
        )
        conn.commit()


def load_document_paths(case_id: str, doc_id: str) -> dict:
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT file_paths FROM documents WHERE case_id = %s AND doc_id = %s", (case_id, doc_id))
        row = cursor.fetchone()
        if row and row[0]:
            try:
                return json.loads(row[0])
            except Exception:
                pass
        return {}
