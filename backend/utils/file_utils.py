"""File path helpers and utilities."""

import json
import re
import aiofiles
from pathlib import Path
from fastapi import UploadFile

BASE_DIR = Path(".")


def get_case_dir(case_id: str) -> Path:
    d = BASE_DIR / "outputs" / case_id
    d.mkdir(parents=True, exist_ok=True)
    return d


async def save_upload(file: UploadFile, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    # Sanitise filename
    safe_name = re.sub(r"[^\w\-_\. ]", "_", file.filename)
    dest = dest_dir / safe_name
    async with aiofiles.open(dest, "wb") as f:
        content = await file.read()
        await f.write(content)
    return dest


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def read_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def cleanup_temp(directory: Path) -> None:
    """Remove a directory and all its contents."""
    import shutil
    if directory.exists():
        shutil.rmtree(directory, ignore_errors=True)
