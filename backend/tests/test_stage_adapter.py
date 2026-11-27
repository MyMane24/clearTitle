from backend.workers.context import StageContext
from backend.workers.stage_adapter import run_stage
from backend.workers.stage_base import ExtractionStage


class _Stage(ExtractionStage):
    def invoke(self, ctx: StageContext) -> dict:
        return {"case_id": ctx.case_id, "doc_id": ctx.doc_id}


def test_run_stage_invokes_with_one_context_and_returns_the_result():
    assert run_stage(_Stage(), task_name="test", case_id="C1", doc_id="D1") == {
        "case_id": "C1",
        "doc_id": "D1",
    }
