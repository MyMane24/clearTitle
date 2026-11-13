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
                "report": "## Conclusion\n\nThe reviewed evidence does not support a reliable conclusion.",
                "cited_documents": [], "required_documents": [],
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

    @patch("backend.services.agent_runtime.CLEARTITLE_MAX_NUDGES", 0)
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

    @patch("backend.services.agent_runtime.dispatch")
    @patch("backend.services.agent_runtime.complete_with_tools")
    def test_evidence_validation_rejection_grants_one_bounded_recovery(self, model, dispatch):
        ctx = self._context()
        model.return_value = {"tool_calls": [{
            "id": "save", "name": "save_transaction_result", "args": {},
        }]}

        def save_after_recovery(context, _name, _args):
            if dispatch.call_count == 1:
                return {"error": "selected document whose complete OCR was not reviewed"}
            context.saved_results.append({"tx_id": "TX1"})
            context.finished = True
            return {"saved": True}

        dispatch.side_effect = save_after_recovery
        run_tool_loop(ctx=ctx, phase="verify", system="system", instruction="task", max_steps=1)

        self.assertEqual(model.call_count, 2)
        self.assertEqual(dispatch.call_count, 2)
        self.assertTrue(ctx.additional_model_calls_used)
        self.assertEqual(ctx.stop_reason, "persisted_result")

    @patch("backend.services.agent_runtime.CLEARTITLE_MAX_NUDGES", 2)
    @patch("backend.services.agent_runtime.complete_with_tools")
    def test_prose_only_turns_are_nudged_a_bounded_number_of_times(self, model):
        model.return_value = {"tool_calls": [], "content": "Prose only"}
        ctx = self._context()
        run_tool_loop(ctx=ctx, phase="verify", system="system", instruction="task", max_steps=8)

        self.assertEqual(model.call_count, 3)  # first turn + 2 nudged retries
        self.assertEqual(ctx.stop_reason, "model_stopped_without_result")
        last_messages = model.call_args.args[0]
        self.assertIn("without calling a tool", last_messages[-1]["content"])

    @patch("backend.services.agent_runtime.CLEARTITLE_MAX_NUDGES", 2)
    @patch("backend.services.agent_runtime.dispatch")
    @patch("backend.services.agent_runtime.complete_with_tools")
    def test_nudged_model_can_still_persist_its_result(self, model, dispatch):
        ctx = self._context()
        model.side_effect = [
            {"tool_calls": [], "content": "All done."},
            {"tool_calls": [{"id": "save", "name": "save_transaction_result", "args": {}}]},
        ]

        def persist(context, _name, _args):
            context.saved_results.append({"tx_id": "TX1"})
            context.finished = True
            return {"saved": True}

        dispatch.side_effect = persist
        run_tool_loop(ctx=ctx, phase="verify", system="system", instruction="task", max_steps=8)

        self.assertEqual(model.call_count, 2)
        self.assertEqual(ctx.stop_reason, "persisted_result")

    @patch("backend.services.agent_runtime.CLEARTITLE_MAX_NUDGES", 0)
    @patch("backend.services.agent_runtime.dispatch", return_value={"ok": True})
    @patch("backend.services.agent_runtime.complete_with_tools")
    def test_tool_results_report_remaining_budget_and_last_call_is_restricted(self, model, _dispatch):
        model.return_value = {"tool_calls": [{"id": "c", "name": "list_documents", "args": {}}]}
        run_tool_loop(ctx=self._context(), phase="verify", system="system", instruction="task", max_steps=4)

        final_call = model.call_args_list[-1]
        offered = {tool["name"] for tool in final_call.kwargs["tools"]}
        self.assertEqual(offered, {"save_transaction_result", "request_missing_documents"})
        self.assertTrue(any("FINAL CALL" in str(m.get("content")) for m in final_call.args[0]))
        tool_messages = [m for m in final_call.args[0] if m.get("role") == "tool"]
        self.assertIn('"calls_remaining": 0', tool_messages[-1]["content"])

    @patch("backend.services.agent_runtime.CLEARTITLE_KEEP_OCR_RESULTS", 1)
    def test_old_ocr_is_cleared_only_after_observations_are_recorded(self):
        import json as _json
        from backend.services.agent_runtime import _prune_stale_ocr

        ctx = ToolContext("CASE1", [], current_tx_id="TX1")

        def ocr(doc_id, start):
            return {"role": "tool", "name": "get_document_text", "tool_call_id": doc_id + str(start),
                    "content": _json.dumps({"doc_id": doc_id, "start_char": start, "total_chars": 99,
                                            "has_more": True, "next_start_char": start + 4, "text": "abcd"})}

        messages = [ocr("DOC1", 0), ocr("DOC2", 0), ocr("DOC2", 4)]
        # Nothing noted yet: nothing may be dropped.
        self.assertEqual(_prune_stale_ocr(ctx, messages), 0)
        ctx.observations.append({"doc_id": "DOC1", "fact": "A sold to B", "pages": None, "quote": None})
        self.assertEqual(_prune_stale_ocr(ctx, messages), 1)
        self.assertTrue(_json.loads(messages[0]["content"])["pruned"])
        self.assertIn("text", _json.loads(messages[1]["content"]))  # DOC2 has no notes yet
        self.assertEqual(ctx.pruned_ranges["DOC1"], {(0, 4)})

    def test_record_observation_requires_read_document_and_reports_quote_match(self):
        docs = [{"doc_id": "DOC1", "filename": "a.pdf", "status": "structured"}]
        ctx = ToolContext("CASE1", docs, current_tx_id="TX1")
        self.assertIn("error", dispatch(ctx, "record_observation", {"doc_id": "DOC1", "fact": "x"}))
        ctx.read_text_ranges["DOC1"] = [(0, 20, 20)]
        ctx.document_text_cache["DOC1"] = "Sold  to  Ramesh   Kumar"
        ok = dispatch(ctx, "record_observation", {"doc_id": "DOC1", "fact": "Buyer", "quote": "sold to ramesh kumar"})
        self.assertTrue(ok["recorded"])
        self.assertTrue(ok["quote_found_in_ocr"])
        miss = dispatch(ctx, "record_observation", {"doc_id": "DOC1", "fact": "Seller", "quote": "not in text"})
        self.assertFalse(miss["quote_found_in_ocr"])

    @patch("backend.services.agent_runtime.dispatch", return_value={
        "error": "invalid transaction result",
        "issues": ["report has a supported validation issue"],
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

    @patch("backend.services.agent_runtime.CLEARTITLE_MAX_NUDGES", 0)
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
