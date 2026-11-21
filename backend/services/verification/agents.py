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
from backend.services.verification.context import compact_history
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
    capabilities=[ProcessHistory(compact_history)],
    retries={"tools": 3, "output": 6},
    name="lead_examiner",
)


@lead_agent.instructions
def playbooks(ctx: RunContext[VerifyDeps]) -> str:
    """Every lawyer playbook (operator-written files, never document text).

    The text is the same on every call, so it forms a stable, cacheable prefix.
    """
    return "PLAYBOOKS\n\n" + skills.all_playbooks()


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
