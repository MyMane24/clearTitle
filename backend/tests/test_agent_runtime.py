import unittest
from unittest.mock import patch

from backend.services.agent_tools import ToolContext
from backend.services.agent_tools import dispatch
from backend.services.agent_runtime import run_tool_loop


class TestBoundedAgentRuntime(unittest.TestCase):
    def _context(self):
        return ToolContext("CASE1", [], current_tx_id="TX1")

    @patch("backend.services.agent_runtime.dispatch")
    @patch("backend.services.agent_runtime.complete_with_tools")
    def test_successful_persistence_ends_run_without_finish_turn(self, model, dispatch):
        ctx = self._context()
        model.return_value = {"tool_calls": [
            {"id": "save", "name": "save_transaction_result", "args": {}},
            {"id": "extra", "name": "list_documents", "args": {}},
        ]}

        def persist(context, name, _args):
            context.saved_results.append({"tx_id": "TX1"})
            context.finished = True
            return {"saved": True}

        dispatch.side_effect = persist
        run_tool_loop(ctx=ctx, phase="verify", system="system", instruction="task", max_steps=8)

        model.assert_called_once()
        dispatch.assert_called_once()
        self.assertEqual(ctx.stop_reason, "persisted_result")

    @patch("backend.services.agent_tools.repo.get_document_raw_text", return_value="Complete deed OCR")
    @patch("backend.services.agent_tools.repo.save_transaction_result")
    @patch("backend.services.agent_tools.repo.get_transaction_result", return_value=None)
    @patch("backend.services.agent_runtime.complete_with_tools")
    def test_real_save_handler_stops_same_response_additional_tools(
        self, model, _prior, save, _ocr,
    ):
        tx = {"tx_id": "TX1", "sequence": 1, "transaction_type": "Gift deed"}
        docs = [{
            "doc_id": "DOC1", "filename": "gift.pdf", "document_type": "GIFT_DEED",
            "status": "structured", "summary": "Gift deed transferring property from A to B.",
        }]
        ctx = ToolContext("CASE1", docs, chain={"transactions": [tx]}, current_tx_id="TX1")
        dispatch(ctx, "record_evidence_requirements", {"requirements": [{
            "document_type": "Gift deed", "reason": "Confirm the transfer instrument.",
        }]})
        dispatch(ctx, "list_documents", {})
        dispatch(ctx, "select_documents", {"doc_ids": ["DOC1"]})
        dispatch(ctx, "get_document_text", {"doc_id": "DOC1", "max_chars": 200000})

        model.return_value = {"tool_calls": [
            {"id": "save", "name": "save_transaction_result", "args": {
                "tx_id": "TX1", "sequence": 1, "status": "INCONCLUSIVE",
                "summary": "The reviewed evidence does not support a reliable conclusion.",
                "findings": [], "required_documents": [],
            }},
            {"id": "extra", "name": "list_documents", "args": {}},
        ]}

        run_tool_loop(ctx=ctx, phase="verify", system="system", instruction="task", max_steps=8)

        save.assert_called_once()
        model.assert_called_once()
        self.assertEqual(ctx.tool_call_counts["list_documents"], 1)
        self.assertEqual(ctx.saved_results[0]["tx_id"], "TX1")
        self.assertEqual(ctx.stop_reason, "persisted_result")

    @patch("backend.services.agent_runtime.dispatch")
    @patch("backend.services.agent_runtime.complete_with_tools")
    def test_missing_evidence_terminates_after_successful_persistence(self, model, dispatch):
        ctx = self._context()
        model.return_value = {"tool_calls": [
            {"id": "missing", "name": "request_missing_documents", "args": {}},
        ]}

        def pause(context, _name, _args):
            context.missing_requests.append({"tx_id": "TX1"})
            context.finished = True
            return {"paused": True}

        dispatch.side_effect = pause
        run_tool_loop(ctx=ctx, phase="verify", system="system", instruction="task", max_steps=8)

        model.assert_called_once()
        self.assertTrue(ctx.finished)

    @patch("backend.services.agent_runtime.dispatch")
    @patch("backend.services.agent_runtime.complete_with_tools")
    def test_model_call_budget_is_enforced_without_nudges(self, model, dispatch):
        model.return_value = {"tool_calls": [{"id": "call", "name": "list_documents", "args": {}}]}
        run_tool_loop(ctx=self._context(), phase="verify", system="system", instruction="task", max_steps=2)

        self.assertEqual(model.call_count, 2)
        self.assertEqual(dispatch.call_count, 2)

    @patch("backend.services.agent_runtime.dispatch", wraps=dispatch)
    @patch("backend.services.agent_runtime.complete_with_tools")
    def test_explicit_budget_extension_grants_one_bounded_continuation(self, model, _dispatch):
        ctx = self._context()
        model.side_effect = [
            {"tool_calls": [{"id": "extend", "name": "request_additional_verification_calls", "args": {
                "next_step": "Read the second page of the cited deed to confirm the property schedule.",
            }}]},
            {"tool_calls": [{"id": "docs", "name": "list_documents", "args": {}}]},
            {"tool_calls": []},
        ]

        run_tool_loop(ctx=ctx, phase="verify", system="system", instruction="task", max_steps=1)

        self.assertEqual(model.call_count, 3)
        self.assertTrue(ctx.additional_model_calls_used)
        self.assertEqual(ctx.stop_reason, "model_stopped_without_result")

    @patch("backend.services.agent_runtime.complete_with_tools")
    def test_no_tool_result_does_not_trigger_result_nudges(self, model):
        model.return_value = {"tool_calls": [], "content": "Prose only"}
        ctx = self._context()
        run_tool_loop(ctx=ctx, phase="verify", system="system", instruction="task", max_steps=8)

        model.assert_called_once()
        self.assertEqual(ctx.stop_reason, "model_stopped_without_result")

    @patch("backend.services.agent_runtime.dispatch", return_value={
        "error": "invalid transaction result",
        "issues": ["findings[0] has a supported validation issue"],
    })
    @patch("backend.services.agent_runtime.complete_with_tools")
    def test_tool_validation_rejection_is_written_to_run_logs(self, model, _dispatch):
        model.return_value = {"tool_calls": [{
            "id": "save", "name": "save_transaction_result", "args": {},
        }]}
        with self.assertLogs("backend.services.agent_runtime", level="WARNING") as captured:
            run_tool_loop(ctx=self._context(), phase="verify", system="system", instruction="task", max_steps=1)

        self.assertTrue(any("agent_tool_rejected" in line for line in captured.output))
        self.assertTrue(any("supported validation issue" in line for line in captured.output))

    def test_identical_successful_tool_call_uses_cached_result(self):
        ctx = self._context()
        ctx.evidence_requirements = [{"document_type": "deed", "reason": "verify"}]
        calls = []
        with patch("backend.services.agent_tools._HANDLERS", {
            "probe": lambda _context, _args: calls.append("called") or {"ok": True},
        }):
            first = dispatch(ctx, "probe", {"doc_id": "DOC1"})
            second = dispatch(ctx, "probe", {"doc_id": "DOC1"})

        self.assertEqual(first, second)
        self.assertEqual(calls, ["called"])
        self.assertEqual(ctx.repeated_tool_calls, 1)

    @patch("backend.services.agent_tools._HANDLERS")
    @patch("backend.services.agent_runtime.complete_with_tools")
    def test_repeated_call_reuses_cached_response_and_loop_continues(self, model, handlers):
        ctx = self._context()
        executions = []
        handlers.get.return_value = lambda _ctx, _args: executions.append(1) or {"ok": True}
        repeated = {"id": "same", "name": "probe", "args": {"doc_id": "DOC1"}}
        model.side_effect = [
            {"tool_calls": [repeated]},
            {"tool_calls": [dict(repeated, id="again")]},
            {"tool_calls": [{"id": "next", "name": "probe", "args": {"doc_id": "DOC2"}}]},
            {"tool_calls": []},
        ]

        run_tool_loop(ctx=ctx, phase="verify", system="system", instruction="task", max_steps=8)

        self.assertEqual(model.call_count, 4)
        self.assertEqual(executions, [1, 1])
        self.assertEqual(ctx.stop_reason, "model_stopped_without_result")
        self.assertEqual(ctx.repeated_tool_calls, 1)
        self.assertIn("duplicate_call", str(model.call_args_list[2]))


if __name__ == "__main__":
    unittest.main()
