"""What every verification tool receives: the Case File, document text and the event feed."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from pydantic_ai.usage import RunUsage

from backend.services.verification.case_file import CaseFile
from backend.services.verification.gates import GateContext

# kind, text, ref -> None. ``kind`` is a short label such as "examine" or "finding".
EventSink = Callable[[str, str, str | None], None]


class TextCache:
    """Loads each document's OCR text once per run."""

    def __init__(self, loader: Callable[[str], str]):
        self._loader = loader
        self._texts: dict[str, str] = {}

    def __call__(self, doc_id: str) -> str:
        if doc_id not in self._texts:
            self._texts[doc_id] = self._loader(doc_id)
        return self._texts[doc_id]


@dataclass
class VerifyDeps:
    """State shared by the Lead's tools during one run.

    Args:
        case: The Case File; tools change it in place and the runner saves it.
        text_of: Returns a document's merged OCR text.
        emit: Adds one line to the live feed.
        examiner_model: Model the Document Examiner runs on (None in tests that
            override it).
        sub_usage: Model usage of Document Examiner runs, kept apart from the
            Lead's own budget.
    """

    case: CaseFile
    text_of: Callable[[str], str]
    emit: EventSink
    examiner_model: object | None = None
    sub_usage: RunUsage = field(default_factory=RunUsage)
    examination_failures: dict[str, int] = field(default_factory=dict)

    @property
    def gate_context(self) -> GateContext:
        return GateContext(case=self.case, text_of=self.text_of)
