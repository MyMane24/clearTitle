"""The model inference layer: the Lead Examiner agent.

The Document Examiner lives in ``examiner.py`` and the report writer in
``report.py``. This module wires the Lead's toolsets, context trimming and
closure gate. To give the Lead a new capability, add its toolset to
``LEAD_TOOLSETS``.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.capabilities import ProcessHistory

from backend.prompts.loader import load_prompt
from backend.services.verification import skills
from backend.services.verification.context import trim_tool_results
from backend.services.verification.deps import VerifyDeps
from backend.services.verification.examiner import examiner_tools
from backend.services.verification.gates import closure_problems
from backend.services.verification.tools import case_file_tools, evidence_tools

LEAD_TOOLSETS = [case_file_tools, evidence_tools, examiner_tools]


class LeadClosure(BaseModel):
    """The Lead's closing summary, accepted only when the closure gate passes."""

    model_config = ConfigDict(extra="forbid")

    summary: str = Field(
        min_length=1, description="What was verified, what was found, and what remains open."
    )


lead_agent = Agent(
    deps_type=VerifyDeps,
    output_type=LeadClosure,
    instructions=load_prompt("verify_lead_system"),
    toolsets=LEAD_TOOLSETS,
    capabilities=[ProcessHistory(trim_tool_results)],
    retries={"tools": 3, "output": 6},
    name="lead_examiner",
)


@lead_agent.instructions
def playbook(ctx: RunContext[VerifyDeps]) -> str:
    """The lead playbook and the skill index (operator-written files, not document text)."""
    return "\n\n".join(
        [
            skills.LEAD_PLAYBOOK.read_text(encoding="utf-8"),
            "SKILL INDEX (load with load_skill):\n" + skills.skill_index(),
        ]
    )


@lead_agent.output_validator
def check_closure(ctx: RunContext[VerifyDeps], closure: LeadClosure) -> LeadClosure:
    """Refuse to close while anything required is left undone."""
    problems = closure_problems(ctx.deps.gate_context)
    if problems:
        raise ModelRetry(
            "The case cannot close yet. Still to do:\n- "
            + "\n- ".join(problems[:20])
            + "\nDo these, then close again."
        )
    return closure
