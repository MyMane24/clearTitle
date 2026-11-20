"""Context engineering: append-only history until compaction, playbooks, readable events."""

from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolCallPart, ToolReturnPart

from backend.services.verification import context, skills
from backend.services.verification.events import ListSink, record_node


def tool_round(index, size=20, args_size=10):
    call = ModelResponse(
        parts=[ToolCallPart("record_issue", {"detail": "d" * args_size}, f"call-{index}")]
    )
    result = ModelRequest(parts=[ToolReturnPart("record_issue", "r" * size, f"call-{index}")])
    return [call, result]


def returns(messages):
    return [
        part.content
        for message in messages
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, ToolReturnPart)
    ]


def test_history_is_unchanged_below_the_threshold(monkeypatch):
    monkeypatch.setattr(context, "VERIFY_COMPACT_AT_CHARS", 10_000)
    messages = [message for index in range(5) for message in tool_round(index)]
    assert context.compact_history(None, messages) is messages  # identical prefix: cacheable


def test_compaction_clears_old_results_and_long_args_but_keeps_the_newest_batch(monkeypatch):
    monkeypatch.setattr(context, "VERIFY_COMPACT_AT_CHARS", 500)
    messages = [m for index in range(5) for m in tool_round(index, size=200, args_size=400)]
    compacted = context.compact_history(None, messages)
    assert returns(compacted) == [context.CLEARED] * 4 + ["r" * 200]
    calls = [p for m in compacted if isinstance(m, ModelResponse) for p in m.parts]
    assert all(call.args == context.CLEARED_ARGS for call in calls[:-1])
    assert calls[-1].args == {"detail": "d" * 400}  # the newest call is intact
    assert len(compacted) == len(messages)  # call/return pairs preserved
    assert messages[1].parts[0].content == "r" * 200  # originals not mutated


def test_after_compaction_history_is_append_only_again(monkeypatch):
    monkeypatch.setattr(context, "VERIFY_COMPACT_AT_CHARS", 1000)  # larger than one batch
    messages = [m for index in range(5) for m in tool_round(index, size=200, args_size=400)]
    compacted = context.compact_history(None, messages)
    grown = [*compacted, *tool_round(9, size=50)]
    assert context.compact_history(None, grown) is grown


def test_all_playbooks_go_into_the_instructions(tmp_path):
    (tmp_path / "skill.md").write_text("# Playbook: Verify\n\nMethod.", encoding="utf-8")
    (tmp_path / "partition").mkdir()
    (tmp_path / "partition" / "skill.md").write_text("# Skill: Partition\n\nChecks.", encoding="utf-8")
    text = skills.all_playbooks(tmp_path)
    assert text.index("# Playbook: Verify") < text.index("# Skill: Partition")


def test_lead_has_no_skill_loading_or_task_tools():
    from backend.services.verification.agents import LEAD_TOOLSETS

    names = {name for toolset in LEAD_TOOLSETS for name in toolset.tools}
    assert "load_skill" not in names and "update_tasks" not in names
    assert {"examine_document", "add_requisition", "record_link_verdict"} <= names


class FakeCallToolsNode:
    def __init__(self, text):
        self.model_response = ModelResponse(parts=[TextPart(text)])


def test_model_text_becomes_a_feed_line(monkeypatch):
    from pydantic_ai import Agent

    monkeypatch.setattr(Agent, "is_call_tools_node", staticmethod(lambda node: True))
    sink = ListSink()
    record_node(FakeCallToolsNode("Checking   the 2010 deed next."), sink)
    assert sink.texts("thinking") == ["Checking the 2010 deed next."]


def test_snapshot_lists_each_documents_recitals_and_unexpected_findings():
    from backend.services.verification import case_file as cf
    from backend.tests.verification_fixtures import new_case_file

    case = new_case_file()
    entry = case.documents["D2010"]
    entry.examined = True
    entry.report = cf.ExaminerReport(
        doc_id="D2010",
        summary="2010 sale deed.",
        recitals=[cf.Fact(topic="title", text="Vendor got it by 2005 partition", page=2, quote="q")],
        unexpected=[cf.Fact(topic="minor", text="A minor co-vendor", page=1, quote="q")],
    )
    text = context.render_case_file(case)
    assert "R p.2: Vendor got it by 2005 partition" in text
    assert "U p.1: A minor co-vendor" in text
    assert "TASKS" not in text
