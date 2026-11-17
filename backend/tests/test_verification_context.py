"""Context engineering: old tool results are cleared, skills are indexed, events are readable."""

from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolCallPart, ToolReturnPart

from backend.services.verification import context, skills
from backend.services.verification.events import ListSink, record_node


def tool_round(index):
    call = ModelResponse(parts=[ToolCallPart("read_pages", {"doc_id": "D"}, f"call-{index}")])
    result = ModelRequest(parts=[ToolReturnPart("read_pages", f"page text {index}", f"call-{index}")])
    return [call, result]


def test_only_the_newest_tool_results_are_kept(monkeypatch):
    monkeypatch.setattr(context, "VERIFY_KEEP_TOOL_RESULTS", 2)
    messages = [message for index in range(5) for message in tool_round(index)]
    trimmed = context.trim_tool_results(None, messages)
    contents = [
        part.content
        for message in trimmed
        if isinstance(message, ModelRequest)
        for part in message.parts
    ]
    assert contents == [context.CLEARED] * 3 + ["page text 3", "page text 4"]
    # Call/return pairing is preserved and the originals are not mutated.
    assert len(trimmed) == len(messages)
    assert messages[1].parts[0].content == "page text 0"


def test_context_stays_bounded_over_many_tool_calls(monkeypatch):
    monkeypatch.setattr(context, "VERIFY_KEEP_TOOL_RESULTS", 3)
    messages = []
    for index in range(50):
        messages = context.trim_tool_results(None, [*messages, *tool_round(index)])
    raw = [
        part.content
        for message in messages
        if isinstance(message, ModelRequest)
        for part in message.parts
        if part.content != context.CLEARED
    ]
    assert raw == ["page text 47", "page text 48", "page text 49"]


def test_skill_index_and_loading(tmp_path):
    (tmp_path / "partition").mkdir()
    (tmp_path / "partition" / "skill.md").write_text(
        "# Skill: Partition\n\nLoad when a partition or family settlement affects title.\n",
        encoding="utf-8",
    )
    assert skills.list_skills(tmp_path) == [
        ("partition", "Load when a partition or family settlement affects title.")
    ]
    assert "Partition" in skills.load_skill("partition", tmp_path)
    for bad in ("../secrets", "missing"):
        try:
            skills.load_skill(bad, tmp_path)
        except KeyError as error:
            assert "Available: partition" in str(error)
        else:
            raise AssertionError(f"{bad} should not load")


class FakeCallToolsNode:
    def __init__(self, text):
        self.model_response = ModelResponse(parts=[TextPart(text)])


def test_model_text_becomes_a_feed_line(monkeypatch):
    from pydantic_ai import Agent

    monkeypatch.setattr(Agent, "is_call_tools_node", staticmethod(lambda node: True))
    sink = ListSink()
    record_node(FakeCallToolsNode("Checking   the 2010 deed next."), sink)
    assert sink.texts("thinking") == ["Checking the 2010 deed next."]


def test_newest_batch_is_kept_whole_and_older_results_fit_a_size_budget(monkeypatch):
    monkeypatch.setattr(context, "VERIFY_KEEP_TOOL_RESULTS", 6)
    monkeypatch.setattr(context, "VERIFY_KEEP_TOOL_CHARS", 25)
    old = [message for index in range(3) for message in tool_round(index)]
    batch_call = ModelResponse(parts=[ToolCallPart("examine_document", {}, f"b{i}") for i in range(4)])
    batch = ModelRequest(
        parts=[ToolReturnPart("examine_document", "x" * 100, f"b{i}") for i in range(4)]
    )
    trimmed = context.trim_tool_results(None, [*old, batch_call, batch])
    assert all(part.content == "x" * 100 for part in trimmed[-1].parts)  # unread batch kept
    older = [part.content for message in trimmed[:-1] if isinstance(message, ModelRequest) for part in message.parts]
    assert older == [context.CLEARED] * 3  # over the size budget


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
