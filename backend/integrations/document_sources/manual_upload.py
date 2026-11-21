"""The manual upload source: the user uploads the requisitioned document."""

from __future__ import annotations

from pathlib import Path

from fastapi import UploadFile

from backend.integrations.document_sources.base import ObtainedFile
from backend.integrations.storage.file_utils import save_upload


class ManualUploadSource:
    name = "manual_upload"

    def __init__(self, files: list[UploadFile]):
        self._files = files

    def can_fulfil(self, requisition: dict) -> bool:
        return bool(self._files)

    async def obtain(self, case_id: str, requisition: dict, dest_dir: Path) -> list[ObtainedFile]:
        obtained = []
        for upload in self._files:
            path = await save_upload(upload, dest_dir)
            obtained.append(ObtainedFile(original_name=upload.filename or path.name, path=path))
        return obtained
