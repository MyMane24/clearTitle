"""File path helpers and utilities."""

import json
import os
import re
import shutil
import aiofiles
from pathlib import Path
from fastapi import HTTPException, UploadFile

BASE_DIR = Path(".")

MAX_UPLOAD_SIZE_MB = int(os.getenv("MAX_UPLOAD_SIZE_MB", "50"))
MAX_UPLOAD_SIZE_BYTES = MAX_UPLOAD_SIZE_MB * 1024 * 1024


def get_case_dir(case_id: str) -> Path:
    d = BASE_DIR / "outputs" / case_id
    d.mkdir(parents=True, exist_ok=True)
    return d


async def save_upload(file: UploadFile, dest_dir: Path, doc_id: str = "") -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^\w\-_\. ]", "_", file.filename)
    if doc_id:
        safe_name = f"{doc_id}_{safe_name}"
    dest = dest_dir / safe_name
    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File '{file.filename}' exceeds maximum upload size of {MAX_UPLOAD_SIZE_MB}MB",
        )
    async with aiofiles.open(dest, "wb") as f:
        await f.write(content)
    return dest


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def delete_case_dir(case_id: str) -> bool:
    """Delete the outputs/{case_id} directory and all its contents."""
    d = BASE_DIR / "outputs" / case_id
    if d.exists():
        shutil.rmtree(d)
        return True
    return False


def read_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

