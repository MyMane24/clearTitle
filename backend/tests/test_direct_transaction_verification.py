import unittest
from types import SimpleNamespace
from unittest.mock import patch

from backend.services.agent_tools import (
    SchemaValidationError,
    ToolContext,
    _canonical_verification,
    _current_transaction_metadata,
    _h_get_transaction,
    _result_compactness_errors,
    _validate_candidate_review,
    dispatch,
    tools_for,
)
from backend.services.cleartitle_agent import (
    _phase_a_transactions,
    _resolve_tx_ref,
    _run,
    _run_with_lock,
    _skip_transaction_locked,
    _verify_instruction,
)


class TestDirectTransactionVerification(unittest.TestCase):
    def setUp(self):
        self.phase_a = {
            "property_identity": {"details": []},
            "title_chain_graph": "Owner A -> Owner B",
            "title_chain": [
                {
                    "chain_position": 1,
                    "documented_transaction": {
                        "transaction_type": "Gift deed",
                        "transaction_number": "REG-1",
                        "summary_points": ["Gift from A to B"],
                        "source_refs": [{"doc_id": "DOC1"}],
                    },
                    "related_events": [],
                },
                {
                    "chain_position": 2,
                    "documented_transaction": {
                        "transaction_type": "Sale deed",
                        "transaction_number": "REG-2",
                        "summary_points": ["Sale from B to C"],
                        "source_refs": [{"doc_id": "DOC2"}],
                    },
                    "related_events": [{"type": "Mortgage", "summary_points": ["Mortgage recorded"]}],
                },
            ],
        }

    def test_phase_a_entries_become_stable_verification_transactions(self):
        transactions = _phase_a_transactions(self.phase_a)
        self.assertEqual([tx["tx_id"] for tx in transactions], ["PA-TC-0001", "PA-TC-0002"])
        self.assertEqual(transactions[0]["transaction_type"], "Gift deed")
        self.assertEqual(transactions[1]["related_events"][0]["type"], "Mortgage")
        self.assertFalse(transactions[0]["is_current_owner_transaction"])
        self.assertTrue(transactions[1]["is_current_owner_transaction"])
        self.assertEqual(_resolve_tx_ref({"transactions": transactions}, "PA-TC-0002"), "PA-TC-0002")
        self.assertEqual(_resolve_tx_ref({"transactions": transactions}, "2"), "PA-TC-0002")

    def test_transaction_lookup_rejects_non_active_transaction_without_reading_its_result(self):
        ctx = ToolContext(
            "CASE1", [], chain={"transactions": _phase_a_transactions(self.phase_a)},
            current_tx_id="PA-TC-0002", phase_a_chain=self.phase_a["title_chain"],
        )
        with patch("backend.services.agent_tools.repo.get_transaction_result") as get_result:
            result = _h_get_transaction(ctx, {"tx_id": "PA-TC-0001"})
        self.assertIn("only the active transaction", result["error"])
        get_result.assert_not_called()

    def test_active_transaction_mismatch_is_rejected_before_persistence(self):
        ctx = ToolContext(
            "CASE1", [], chain={"transactions": _phase_a_transactions(self.phase_a)},
            current_tx_id="PA-TC-0002", phase_a_chain=self.phase_a["title_chain"],
        )
        with self.assertRaisesRegex(Exception, "tx_id does not match"):
            _canonical_verification(ctx, {
                "tx_id": "PA-TC-0001", "sequence": 1, "status": "INCONCLUSIVE",
                "summary": "This is not the active transaction.", "findings": [],
            })

    def test_legacy_dependency_data_is_not_carried_into_active_canonical_result(self):
        ctx = ToolContext(
            "CASE1", [], chain={"transactions": _phase_a_transactions(self.phase_a)},
            current_tx_id="PA-TC-0002", phase_a_chain=self.phase_a["title_chain"],
        )
        with patch("backend.services.agent_tools.repo.get_transaction_result", return_value=None):
            canonical = _canonical_verification(ctx, {
                "tx_id": "PA-TC-0002", "sequence": 2, "status": "INCONCLUSIVE",
                "summary": "The active transaction was assessed on its evidence.", "findings": [],
            })
        self.assertNotIn("historical_dependencies", canonical)

    def test_phase_a_preserves_previously_assigned_transaction_ids(self):
        chain = {"title_chain": [{
            "tx_id": "T01",
            "chain_position": 1,
            "documented_transaction": {"transaction_type": "Sale"},
        }]}
        self.assertEqual(_phase_a_transactions(chain)[0]["tx_id"], "T01")

    def test_legacy_transaction_id_uses_its_chain_entry_and_sequence(self):
        from backend.services.agent_tools import _canonical_verification, _phase_a_entry_for_id

        entry = {
            "tx_id": "T01", "chain_position": 1,
            "documented_transaction": {"transaction_type": "Sale"},
        }
        ctx = ToolContext("CASE1", [], current_tx_id="T01", phase_a_chain=[entry])
        self.assertIs(_phase_a_entry_for_id(ctx, "T01"), entry)
        with patch("backend.services.agent_tools.repo.get_transaction_result", return_value=None):
            payload = _canonical_verification(ctx, {
                "tx_id": "T01", "sequence": 1, "status": "PENDING_NOT_VERIFIED",
                "summary": "Original deed is outstanding.", "findings": [],
                "required_documents": [{"document_type": "Original deed", "reason": "Verify transfer."}],
            }, force_pending=True)
        self.assertEqual(payload["tx_id"], "T01")
        self.assertEqual(payload["sequence"], 1)

    def test_succession_death_date_is_not_emitted_as_instrument_execution_date(self):
        chain = {"title_chain": [{
            "chain_position": 1,
            "documented_transaction": {
                "transaction_type": "Succession on death",
                "executed_date": "13 January 1981",
                "summary_points": ["Vijayabai died on 13 January 1981."],
            },
        }]}
        transaction = _phase_a_transactions(chain)[0]
        ctx = ToolContext("CASE1", [], phase_a_chain=chain["title_chain"], current_tx_id=transaction["tx_id"])
        self.assertIsNone(transaction["executed_date"])
        self.assertNotIn("executed_date", _current_transaction_metadata(ctx, transaction["tx_id"]))

    def test_transaction_metadata_exposes_reported_parties_from_chain_summary(self):
        transaction = {
            "tx_id": "T01", "sequence": 1, "transaction_type": "Sale deed",
            "summary_points": ["Meena Kulkarni conveyed the southern portion to Anant Mankikar."],
        }
        ctx = ToolContext("CASE1", [], chain={"transactions": [transaction]}, current_tx_id="T01")
        metadata = _current_transaction_metadata(ctx, "T01")
        self.assertEqual(metadata["vendors"], ["Meena Kulkarni"])
        self.assertEqual(metadata["purchasers"], ["Anant Mankikar"])

    def test_succession_and_later_partition_remain_separate_transactions(self):
        chain = {"title_chain": [
            {"chain_position": 1, "documented_transaction": {
                "transaction_type": "Succession on death",
                "executed_date": "13 January 1981",
                "summary_points": ["The recital reports Vijayabai's death and succession."],
            }},
            {"chain_position": 2, "documented_transaction": {
                "transaction_type": "Partition",
                "executed_date": None,
                "summary_points": ["The recital reports partition and Mutation Entry 4930 in 1988."],
            }},
        ]}
        transactions = _phase_a_transactions(chain)
        self.assertEqual([item["tx_id"] for item in transactions], ["PA-TC-0001", "PA-TC-0002"])
        self.assertIn("Succession", transactions[0]["transaction_type"])
        self.assertEqual(transactions[0]["executed_date"], None)
        self.assertEqual(transactions[1]["transaction_type"], "Partition")
        self.assertIsNone(transactions[1]["executed_date"])

    def test_verification_instruction_includes_skill_and_applicable_rules(self):
        instruction = _verify_instruction(_phase_a_transactions(self.phase_a)[0])
        self.assertIn("MANDATORY TRANSACTION-VERIFICATION SKILL", instruction)
        self.assertIn("Gift deed", instruction)
        self.assertNotIn("persisted TODO", instruction)

    @patch("backend.services.cleartitle_agent.repo.get_transaction_result", return_value=None)
    @patch("backend.services.cleartitle_agent.repo.save_transaction_result")
    @patch("backend.services.cleartitle_agent.run_tool_loop")
    def test_budget_exhaustion_saves_safe_inconclusive_checkpoint(self, run_loop, save, _prior):
        from backend.services.cleartitle_agent import _VERIFY_MAX_STEPS, _verify_transaction

        transaction = _phase_a_transactions(self.phase_a)[0]

        def exhaust(**kwargs):
            kwargs["ctx"].stop_reason = "model_call_budget_exhausted"

        run_loop.side_effect = exhaust
        ctx = _verify_transaction("CASE1", [], self.phase_a, transaction)

        self.assertEqual(ctx.saved_results[0]["status"], "INCONCLUSIVE")
        self.assertIn("no verification claim", ctx.saved_results[0]["summary"])
        self.assertEqual(run_loop.call_args.kwargs["max_steps"], _VERIFY_MAX_STEPS)
        save.assert_called_once()

    def test_result_quality_rejects_duplication_but_never_discards_material_length(self):
        repeated = {
            "summary": "The purchaser identity remains unresolved.",
            "findings": [{
                "title": "Identity discrepancy",
                "details": "The purchaser identity remains unresolved.",
                "evidence": [{"doc_id": "DOC1", "pages": "2"}],
            }],
            "required_documents": [{
                "document_type": "Identity and authority evidence",
                "reason": "The purchaser identity remains unresolved.",
            }],
        }
        errors = _result_compactness_errors(repeated)
        self.assertTrue(any("summary repeats a finding" in error for error in errors))
        requirement_error = next(error for error in errors if "required_documents[0].reason" in error)
        self.assertIn("without changing or abbreviating document_type", requirement_error)
        self.assertEqual(
            repeated["required_documents"][0]["document_type"],
            "Identity and authority evidence",
        )

        longer_conclusion = {
            "summary": " ".join(["conclusion"] * 60),
            "findings": [], "required_documents": [],
        }
        self.assertEqual(_result_compactness_errors(longer_conclusion), [])
        long_material_finding = {
            "summary": "The active conveyance remains pending on one material issue.",
            "findings": [{
                "title": "Material documentary discrepancy",
                "details": " ".join(["material"] * 120) + ".",
                "evidence": [{"doc_id": "DOC1", "pages": "1-4"}],
            }],
            "required_documents": [],
        }
        self.assertEqual(_result_compactness_errors(long_material_finding), [])

        multi_sentence_finding = {
            "summary": "The record supports the active transfer.",
            "findings": [{
                "title": "Material limitation",
                "details": "First material fact. Second material fact. Third material fact. Fourth material fact.",
                "evidence": [{"doc_id": "DOC1", "pages": "1-4"}],
            }],
            "required_documents": [],
        }
        self.assertEqual(_result_compactness_errors(multi_sentence_finding), [])

    def test_compaction_validation_preserves_material_findings_and_citations(self):
        finding = {
            "title": "Purchaser identity discrepancy",
            "details": "DOC1 identifies Shrinath Battal through a GPA holder; DOC2 recites Anant Mankikar. The evidence does not establish that these are the same purchaser, so the transferor's interest remains unverified.",
            "evidence": [{"doc_id": "DOC1", "pages": "1"}, {"doc_id": "DOC2", "pages": "4"}],
        }
        payload = {
            "summary": "The active sale is pending because the seller's supporting title link is unresolved.",
            "findings": [finding],
            "required_documents": [{
                "document_type": (
                    "Complete registered sale deed no. 1415/1990-91 dated 18 August 1990, "
                    "including the operative general power of attorney and any contemporaneous "
                    "identity, assignment, or rectification record establishing whether "
                    "Shrinath Battal alias Larkib acquired this exact 4,500 sq. ft. Plot No. 40 "
                    "schedule as Anant Dattatraya Mankikar, with registration endorsement"
                ),
                "reason": (
                    "Resolve the purchaser identity and representative authority, and establish "
                    "whether the instrument covers the same 4,500 sq. ft. parcel before relying "
                    "on Mankikar's later conveyance."
                ),
            }],
        }
        self.assertEqual(_result_compactness_errors(payload), [])
        self.assertIn("these are the same purchaser", payload["findings"][0]["details"])
        self.assertIn("1415/1990-91", payload["required_documents"][0]["document_type"])
        self.assertIn("4,500 sq. ft.", payload["required_documents"][0]["document_type"])
        self.assertEqual([ref["doc_id"] for ref in payload["findings"][0]["evidence"]], ["DOC1", "DOC2"])

    def test_sentence_limit_does_not_split_common_property_abbreviations(self):
        payload = {
            "summary": "The deed covers Plot 40 in R.S. No. 191/4, measuring 4,500 sq. ft.",
            "findings": [],
            "required_documents": [],
        }
        self.assertFalse(any("1-2 sentence" in error for error in _result_compactness_errors(payload)))

    def test_system_prompt_and_skill_require_the_requested_transaction_workflow(self):
        from backend.prompts.loader import load_prompt
        from backend.services.cleartitle_agent import verification_skill_path

        system = load_prompt("agent_system")
        skill = verification_skill_path().read_text(encoding="utf-8")
        for phrase in (
            "Read the complete supplied transaction object", "all eligible supporting-document summaries and metadata",
            "every OCR chunk", "registration remains unverified", "same result",
            "do not copy an upstream transaction's finding", "never ask the user to upload a document that is already available",
            "requirement-to-candidate matches", "Do not call different registration numbers a conflict",
            "max_chars=200000", "100–180 words for ordinary narrative text",
            "Never abbreviate it to fit the narrative budget", "The EC is not an eligible Phase B source",
        ):
            self.assertIn(phrase.casefold(), system.casefold())
        for phrase in (
            "execute these steps in order", "complete stored OCR has been read", "Instrument found",
            "conditions, exceptions", "OCR is truncated", "Do not duplicate an earlier transaction's finding",
            "do not ask the user to upload a matching document that is already in the database",
        ):
            self.assertIn(phrase.casefold(), skill.casefold())

    def test_verification_tools_have_no_plan_or_todo_tools(self):
        names = {tool["name"] for tool in tools_for("verify")}
        self.assertNotIn("save_verification_plan", names)
        self.assertNotIn("update_todo_step", names)
        self.assertIn("request_missing_documents", names)
        self.assertIn("save_transaction_result", names)
        self.assertIn("record_evidence_requirements", names)
        self.assertIn("select_documents", names)

    def test_verify_finish_is_blocked_until_transaction_result_is_saved(self):
        ctx = ToolContext("CASE1", [], current_tx_id="PA-TC-0001")
        response = dispatch(ctx, "finish", {})
        self.assertIn("no saved result", response["error"])
        self.assertFalse(ctx.finished)
        ctx.saved_results.append({"tx_id": "PA-TC-0001"})
        self.assertEqual(dispatch(ctx, "finish", {}), {"ok": True})
        self.assertTrue(ctx.finished)

    @patch("backend.services.agent_tools.repo.get_document_raw_text", return_value="Full deed OCR")
    def test_verification_requires_requirements_then_summary_selection_before_ocr(self, get_text):
        docs = [{
            "doc_id": "DOC1", "filename": "gift.pdf", "document_type": "GIFT_DEED",
            "status": "structured", "summary": "Registered gift deed from A to B.",
        }]
        tx = _phase_a_transactions(self.phase_a)[0]
        ctx = ToolContext("CASE1", docs, chain={"transactions": [tx]}, current_tx_id=tx["tx_id"])

        self.assertIn("record evidence requirements", dispatch(ctx, "list_documents", {})["error"])
        self.assertIn("non-empty", dispatch(ctx, "record_evidence_requirements", {"requirements": []})["error"])
        dispatch(ctx, "record_evidence_requirements", {"requirements": [
            {"document_type": "Gift deed", "reason": "Confirm transfer instrument"},
        ]})
        listed = dispatch(ctx, "list_documents", {})
        self.assertEqual(listed["documents"][0]["doc_id"], "DOC1")
        self.assertEqual(listed["requirement_matches"][0]["candidates"][0]["doc_id"], "DOC1")
        self.assertIn("select this document", dispatch(ctx, "get_document_text", {"doc_id": "DOC1"})["error"])
        dispatch(ctx, "select_documents", {"doc_ids": ["DOC1"]})
        self.assertEqual(dispatch(ctx, "get_document_text", {"doc_id": "DOC1"})["text"], "Full deed OCR")
        get_text.assert_called_once_with("CASE1", "DOC1")

    def test_transaction_document_search_excludes_chain_only_encumbrance_certificate(self):
        docs = [
            {
                "doc_id": "DOC_DEED", "filename": "gift.pdf", "document_type": "GIFT_DEED",
                "status": "structured", "summary": "Registered gift deed transferring the parcel from A to B.",
            },
            {
                "doc_id": "DOC_EC", "filename": "encumbrance.pdf", "document_type": "ENCUMBRANCE_CERTIFICATE",
                "status": "structured", "summary": "Gift deed and sale for the same parcel; mortgage also recorded.",
            },
        ]
        tx = _phase_a_transactions(self.phase_a)[0]
        ctx = ToolContext("CASE1", docs, chain={"transactions": [tx]}, current_tx_id=tx["tx_id"])
        dispatch(ctx, "record_evidence_requirements", {"requirements": [{
            "document_type": "Gift deed", "reason": "Confirm the transfer instrument for this transaction.",
        }]})

        listed = dispatch(ctx, "list_documents", {})
        self.assertEqual([item["doc_id"] for item in listed["documents"]], ["DOC_DEED"])
        self.assertEqual(ctx.listed_document_ids, {"DOC_DEED"})
        self.assertIn("not as transaction-verification evidence", listed["scope"].casefold())
        self.assertIn("select only documents", listed["scope"].casefold())
        self.assertEqual(
            [item["doc_id"] for item in listed["requirement_matches"][0]["candidates"]],
            ["DOC_DEED"],
        )
        self.assertNotIn("DOC_EC", str(listed["requirement_matches"]))
        self.assertIn("select only document IDs", dispatch(ctx, "select_documents", {
            "doc_ids": ["DOC_EC"],
        })["error"])

    def test_transaction_evidence_cannot_cite_ec_even_when_it_exists_in_case(self):
        tx = _phase_a_transactions(self.phase_a)[0]
        docs = [
            {"doc_id": "DOC1", "filename": "gift.pdf", "document_type": "GIFT_DEED", "status": "structured"},
            {"doc_id": "DOC_EC", "filename": "EC.pdf", "document_type": "ENCUMBRANCE_CERTIFICATE", "status": "structured"},
        ]
        ctx = ToolContext("CASE1", docs, chain={"transactions": [tx]}, current_tx_id=tx["tx_id"])
        ctx.selected_document_ids = {"DOC1"}
        ctx.read_text_ranges["DOC1"] = [(0, 1, 1)]
        with self.assertRaises(SchemaValidationError) as error:
            _canonical_verification(ctx, {
                "tx_id": tx["tx_id"], "sequence": 1, "status": "ISSUES_IDENTIFIED",
                "summary": "A discrepancy is identified.",
                "findings": [{
                    "title": "Claim", "details": "The EC supports a fact.",
                    "evidence": [{"doc_id": "DOC_EC", "pages": "1"}],
                }],
                "required_documents": [],
            })

        self.assertIn("title-chain-only", str(error.exception))

    def test_verification_transaction_hides_phase_a_source_references(self):
        docs = [{
            "doc_id": "DOC1", "filename": "gift.pdf", "document_type": "GIFT_DEED",
            "status": "structured", "summary": "Registered gift deed.",
        }, {
            "doc_id": "DOC_EC", "filename": "EC.pdf", "document_type": "ENCUMBRANCE_CERTIFICATE",
            "status": "structured", "summary": "Chain event index.",
        }]
        tx = _phase_a_transactions(self.phase_a)[0]
        ctx = ToolContext("CASE1", docs, current_tx_id=tx["tx_id"], phase_a_chain=self.phase_a["title_chain"])
        result = dispatch(ctx, "get_transaction", {})

        self.assertNotIn("source_refs", result["transaction"])
        self.assertNotIn("DOC1", str(result["transaction"]))

    @patch("backend.services.agent_tools.repo.get_document_metadata", return_value={
        "doc_id": "DOC1", "filename": "sale.pdf", "document_type": "SALE_DEED",
        "summary": "Sale deed", "structured_data": {"parties": ["extracted"]},
    })
    def test_candidate_metadata_requires_summary_search_and_excludes_extraction(self, get_metadata):
        docs = [{"doc_id": "DOC1", "filename": "sale.pdf", "document_type": "SALE_DEED", "summary": "Sale deed"}]
        ctx = ToolContext("CASE1", docs, current_tx_id="TX1")
        self.assertIn("search document summaries", dispatch(ctx, "get_document_metadata", {"doc_id": "DOC1"})["error"])
        ctx.evidence_requirements = [{"document_type": "Sale deed", "reason": "Verify conveyance"}]
        dispatch(ctx, "list_documents", {})
        metadata = dispatch(ctx, "get_document_metadata", {"doc_id": "DOC1"})
        self.assertNotIn("structured_data", metadata)
        self.assertEqual(metadata["document_type"], "SALE_DEED")
        get_metadata.assert_called_once_with("CASE1", "DOC1")

    @patch("backend.services.agent_tools.repo.get_document_raw_text", return_value="abcdefghij")
    def test_verified_result_requires_full_ocr_of_selected_supporting_documents(self, get_text):
        tx = _phase_a_transactions(self.phase_a)[0]
        docs = [{"doc_id": "DOC1", "filename": "gift.pdf", "status": "structured", "summary": "Gift deed"}]
        ctx = ToolContext("CASE1", docs, chain={"transactions": [tx]}, current_tx_id=tx["tx_id"])
        dispatch(ctx, "record_evidence_requirements", {"requirements": [{"document_type": "Gift deed", "reason": "Verify transfer"}]})
        dispatch(ctx, "list_documents", {})
        dispatch(ctx, "select_documents", {"doc_ids": ["DOC1"]})
        partial = dispatch(ctx, "get_document_text", {"doc_id": "DOC1", "max_chars": 4})
        self.assertTrue(partial["has_more"])
        with patch("backend.services.agent_tools.repo.get_transaction_result", return_value=None), patch(
            "backend.services.agent_tools.repo.save_transaction_result"
        ) as save:
            response = dispatch(ctx, "save_transaction_result", {
                "tx_id": tx["tx_id"], "sequence": 1,
                "status": "VERIFIED_WITH_AVAILABLE_EVIDENCE", "summary": "The deed matches.",
            })
            self.assertIn("full OCR", response["error"])
            save.assert_not_called()
            dispatch(ctx, "get_document_text", {"doc_id": "DOC1", "start_char": 4, "max_chars": 6})
            response = dispatch(ctx, "save_transaction_result", {
                "tx_id": tx["tx_id"], "sequence": 1,
                "status": "VERIFIED_WITH_AVAILABLE_EVIDENCE", "summary": "The deed matches.",
            })
            self.assertTrue(response["saved"])
            save.assert_called_once()
        self.assertEqual(get_text.call_count, 1)
        self.assertTrue(ctx.finished)

    @patch("backend.services.agent_tools.repo.get_document_raw_text", return_value="abcdefghij")
    def test_ocr_is_loaded_once_and_overlapping_ranges_are_rejected(self, get_text):
        tx = _phase_a_transactions(self.phase_a)[0]
        docs = [{"doc_id": "DOC1", "status": "structured", "summary": "Gift deed"}]
        ctx = ToolContext("CASE1", docs, chain={"transactions": [tx]}, current_tx_id=tx["tx_id"])
        dispatch(ctx, "record_evidence_requirements", {"requirements": [{
            "document_type": "Gift deed", "reason": "Verify transfer",
        }]})
        dispatch(ctx, "list_documents", {})
        dispatch(ctx, "select_documents", {"doc_ids": ["DOC1"]})

        first = dispatch(ctx, "get_document_text", {"doc_id": "DOC1", "max_chars": 5})
        overlap = dispatch(ctx, "get_document_text", {
            "doc_id": "DOC1", "start_char": 4, "max_chars": 4,
        })
        second = dispatch(ctx, "get_document_text", {
            "doc_id": "DOC1", "start_char": 5, "max_chars": 5,
        })

        self.assertEqual(first["text"], "abcde")
        self.assertIn("overlaps", overlap["error"])
        self.assertEqual(second["text"], "fghij")
        get_text.assert_called_once_with("CASE1", "DOC1")

    @patch("backend.services.agent_tools.repo.get_document_raw_text", side_effect=["old OCR", "new OCR"])
    def test_new_resume_context_does_not_reuse_stale_ocr_cache(self, get_text):
        tx = _phase_a_transactions(self.phase_a)[0]
        docs = [{"doc_id": "DOC1", "status": "structured", "summary": "Gift deed"}]
        outputs = []
        for _ in range(2):
            ctx = ToolContext("CASE1", docs, chain={"transactions": [tx]}, current_tx_id=tx["tx_id"])
            dispatch(ctx, "record_evidence_requirements", {"requirements": [{
                "document_type": "Gift deed", "reason": "Verify transfer",
            }]})
            dispatch(ctx, "list_documents", {})
            dispatch(ctx, "select_documents", {"doc_ids": ["DOC1"]})
            outputs.append(dispatch(ctx, "get_document_text", {"doc_id": "DOC1"})["text"])

        self.assertEqual(outputs, ["old OCR", "new OCR"])
        self.assertEqual(get_text.call_count, 2)

    def test_candidate_search_matches_partnership_deed_from_summary_not_just_filename(self):
        docs = [{
            "doc_id": "DOC6", "filename": "scan_006.pdf", "document_type": "PARTNERSHIP_DEED",
            "status": "structured", "summary": "Deed constituting Sapthagiri Associates and naming its partners.",
        }]
        tx = _phase_a_transactions(self.phase_a)[1]
        ctx = ToolContext("CASE1", docs, chain={"transactions": [tx]}, current_tx_id=tx["tx_id"])
        dispatch(ctx, "record_evidence_requirements", {"requirements": [{
            "document_type": "Partnership deed and partner authority",
            "reason": "Confirm the firm and its partners' authority to convey.",
        }]})
        result = dispatch(ctx, "list_documents", {})
        candidates = result["requirement_matches"][0]["candidates"]
        self.assertEqual([candidate["doc_id"] for candidate in candidates], ["DOC6"])
        self.assertIn("Sapthagiri Associates", candidates[0]["summary"])

    @patch("backend.services.agent_tools.repo.get_document_raw_text", return_value="Entire evidence text")
    @patch("backend.services.agent_tools.repo.save_transaction_result")
    @patch("backend.services.agent_tools.repo.get_transaction_result", return_value=None)
    def test_each_matching_uploaded_candidate_must_be_read_before_result_save(
        self, _prior, save, _get_text
    ):
        tx = _phase_a_transactions(self.phase_a)[1]
        docs = [
            {"doc_id": "DOC_DEED", "filename": "deed.pdf", "document_type": "SALE_DEED",
             "status": "structured", "summary": "Sale deed for Flat G-04."},
            {"doc_id": "DOC_PARTNERS", "filename": "partners.pdf", "document_type": "PARTNERSHIP_DEED",
             "status": "structured", "summary": "Sapthagiri Associates partners and authority."},
        ]
        ctx = ToolContext("CASE1", docs, chain={"transactions": [tx]}, current_tx_id=tx["tx_id"])
        dispatch(ctx, "record_evidence_requirements", {"requirements": [
            {"document_type": "Sale deed G-04", "reason": "Confirm unit conveyance."},
            {"document_type": "Partnership deed", "reason": "Confirm firm and signatory authority."},
        ]})
        dispatch(ctx, "list_documents", {})
        dispatch(ctx, "select_documents", {"doc_ids": ["DOC_DEED"]})
        dispatch(ctx, "get_document_text", {"doc_id": "DOC_DEED"})
        response = dispatch(ctx, "save_transaction_result", {
            "tx_id": tx["tx_id"], "sequence": 2,
            "status": "INCONCLUSIVE", "summary": "Review is incomplete.",
            "findings": [], "required_documents": [],
        })
        self.assertIn("review each matching uploaded candidate", response["error"])
        self.assertEqual(response["candidate_doc_ids"], ["DOC_PARTNERS"])
        save.assert_not_called()

    def test_matching_unprocessed_candidate_is_reported_not_treated_as_absent(self):
        docs = [{
            "doc_id": "DOC_PARTNERS", "filename": "partners.pdf",
            "document_type": "PARTNERSHIP_DEED", "status": "skipped",
            "summary": "Sapthagiri Associates partnership deed and partner names.",
        }]
        tx = _phase_a_transactions(self.phase_a)[1]
        ctx = ToolContext("CASE1", docs, chain={"transactions": [tx]}, current_tx_id=tx["tx_id"])
        dispatch(ctx, "record_evidence_requirements", {"requirements": [{
            "document_type": "Partnership deed", "reason": "Check Sapthagiri partners authority."}],
        })
        dispatch(ctx, "list_documents", {})
        issue = _validate_candidate_review(ctx)
        self.assertIn("not processed", issue["error"])
        self.assertEqual(issue["candidate_doc_ids"], ["DOC_PARTNERS"])

    def test_registration_number_in_distinct_instrument_is_not_a_candidate_conflict(self):
        docs = [{
            "doc_id": "DECL", "filename": "declaration.pdf", "document_type": "DECLARATION",
            "status": "structured", "summary": "Apartment declaration instrument 10617 dated 9 November 2015.",
        }, {
            "doc_id": "DEED", "filename": "sale.pdf", "document_type": "SALE_DEED",
            "status": "structured", "summary": "Separate G-04 sale instrument 9762 dated 21 October 2015.",
        }]
        tx = _phase_a_transactions(self.phase_a)[1]
        ctx = ToolContext("CASE1", docs, chain={"transactions": [tx]}, current_tx_id=tx["tx_id"])
        dispatch(ctx, "record_evidence_requirements", {"requirements": [{
            "document_type": "G-04 sale deed instrument 9762",
            "reason": "Identify the distinct conveyance and its own registration particulars.",
        }]})
        candidates = dispatch(ctx, "list_documents", {})["requirement_matches"][0]["candidates"]
        self.assertEqual([candidate["doc_id"] for candidate in candidates], ["DEED"])

    @patch("backend.services.agent_tools.repo.get_document_raw_text", return_value="")
    def test_missing_full_ocr_is_not_returned_as_an_empty_success(self, _get_text):
        tx = _phase_a_transactions(self.phase_a)[0]
        docs = [{"doc_id": "DOC1", "status": "structured", "summary": "Gift deed"}]
        ctx = ToolContext("CASE1", docs, chain={"transactions": [tx]}, current_tx_id=tx["tx_id"])
        dispatch(ctx, "record_evidence_requirements", {"requirements": [{"document_type": "Gift deed", "reason": "Verify transfer"}]})
        dispatch(ctx, "list_documents", {})
        dispatch(ctx, "select_documents", {"doc_ids": ["DOC1"]})
        response = dispatch(ctx, "get_document_text", {"doc_id": "DOC1"})
        self.assertIn("no stored OCR text", response["error"])

    @patch("backend.services.agent_tools.repo.save_transaction_result")
    @patch("backend.services.agent_tools.repo.get_transaction_result", return_value=None)
    def test_pending_saved_result_with_missing_documents_pauses_transaction(self, get_result, save_result):
        tx = _phase_a_transactions(self.phase_a)[0]
        ctx = ToolContext("CASE1", [], chain={"transactions": [tx]}, current_tx_id=tx["tx_id"])
        dispatch(ctx, "record_evidence_requirements", {"requirements": [{
            "document_type": "Certified sale deed", "reason": "Verify the transferor's interest.",
        }]})
        dispatch(ctx, "list_documents", {})

        result = dispatch(ctx, "save_transaction_result", {
            "tx_id": "PA-TC-0001",
            "sequence": 1,
            "status": "PENDING_NOT_VERIFIED",
            "summary": "The primary deed is unavailable, so this transfer remains unverified.",
            "required_documents": [{
                "document_type": "Certified sale deed",
                "reason": "Verify the transferor's interest.",
            }],
        })

        self.assertTrue(result["paused"])
        self.assertEqual(ctx.missing_requests[0]["tx_id"], "PA-TC-0001")
        self.assertEqual(ctx.missing_requests[0]["documents"][0]["document_type"], "Certified sale deed")
        saved = save_result.call_args.kwargs["verification"]
        self.assertIn("required_documents", saved)
        self.assertNotIn("missing_documents", saved)
        self.assertNotIn("conclusion", saved)
        save_result.assert_called_once()

    @patch("backend.services.agent_tools.repo.save_transaction_result")
    @patch("backend.services.agent_tools.repo.get_transaction_result", return_value=None)
    def test_pending_without_required_documents_is_rejected_instead_of_silent_pause(self, _get_result, save_result):
        tx = _phase_a_transactions(self.phase_a)[0]
        ctx = ToolContext("CASE1", [], chain={"transactions": [tx]}, current_tx_id=tx["tx_id"])
        dispatch(ctx, "record_evidence_requirements", {"requirements": [{
            "document_type": "Certified deed", "reason": "Verify the transfer.",
        }]})
        dispatch(ctx, "list_documents", {})

        response = dispatch(ctx, "save_transaction_result", {
            "tx_id": tx["tx_id"], "sequence": 1, "status": "PENDING_NOT_VERIFIED",
            "summary": "The result cannot be verified yet.", "required_documents": [],
        })

        self.assertIn("requires at least one specific", response["error"])
        self.assertFalse(ctx.finished)
        self.assertEqual(ctx.missing_requests, [])
        save_result.assert_not_called()

    @patch("backend.services.agent_tools.repo.get_document_raw_text", return_value="Complete matching deed OCR")
    @patch("backend.services.agent_tools.repo.save_transaction_result")
    @patch("backend.services.agent_tools.repo.get_transaction_result", return_value=None)
    def test_missing_request_is_blocked_until_matching_uploaded_candidate_is_inspected(self, _get_result, save_result, _get_text):
        tx = _phase_a_transactions(self.phase_a)[1]
        docs = [{
            "doc_id": "DOC021", "filename": "sale.pdf", "document_type": "SALE_DEED",
            "status": "structured", "summary": "Sale deed dated 21 October 2015 conveys G-04 from Sapthagiri Associates to Chandrashekhar Hadimani.",
        }]
        ctx = ToolContext("CASE1", docs, chain={"transactions": [tx]}, current_tx_id=tx["tx_id"])
        dispatch(ctx, "record_evidence_requirements", {"requirements": [{
            "document_type": "G-04 sale deed dated 21 October 2015 from Sapthagiri Associates to Chandrashekhar Hadimani",
            "reason": "Verify the reported sale.",
        }]})
        dispatch(ctx, "list_documents", {})
        response = dispatch(ctx, "request_missing_documents", {
            "tx_id": tx["tx_id"], "sequence": 2, "summary": "The sale remains unverified.",
            "required_documents": [{
                "document_type": "G-04 sale deed dated 21 October 2015 from Sapthagiri Associates to Chandrashekhar Hadimani",
                "reason": "Verify the reported sale.",
            }],
        })
        self.assertIn("matching uploaded candidate", response["error"])
        self.assertEqual(response["candidates"][0]["doc_id"], "DOC021")
        save_result.assert_not_called()

        dispatch(ctx, "select_documents", {"doc_ids": ["DOC021"]})
        dispatch(ctx, "get_document_text", {"doc_id": "DOC021"})
        response = dispatch(ctx, "request_missing_documents", {
            "tx_id": tx["tx_id"], "sequence": 2, "summary": "The inspected deed is insufficient for this question.",
            "required_documents": [{
                "document_type": "Certified registration endorsement",
                "reason": "The deed OCR does not establish the registration endorsement.",
            }],
        })
        self.assertTrue(response["paused"])
        save_result.assert_called_once()

    @patch("backend.services.agent_tools.repo.get_transaction_result", return_value=None)
    def test_required_document_cannot_be_attached_to_a_different_transaction(self, _get_result):
        tx = _phase_a_transactions(self.phase_a)[1]
        ctx = ToolContext("CASE1", [], chain={"transactions": [tx]}, current_tx_id=tx["tx_id"])
        ctx.documents_listed = True
        ctx.evidence_requirements = [{"document_type": "Sale deed", "reason": "Verify this transaction"}]
        response = dispatch(ctx, "request_missing_documents", {
            "tx_id": tx["tx_id"], "sequence": 2, "summary": "Pending evidence.",
            "required_documents": [{
                "document_type": "Sale deed", "reason": "Verify a later transfer.",
                "for_transaction": "PA-TC-0009",
            }],
        })
        self.assertIn("not active transaction", response["error"])

    @patch("backend.services.agent_tools.repo.get_transaction_result", return_value=None)
    def test_missing_document_tool_rejects_empty_request(self, _get_result):
        tx = _phase_a_transactions(self.phase_a)[0]
        ctx = ToolContext("CASE1", [], chain={"transactions": [tx]}, current_tx_id=tx["tx_id"])
        response = dispatch(ctx, "request_missing_documents", {
            "tx_id": tx["tx_id"], "sequence": 1,
            "summary": "Evidence is required.", "required_documents": [],
        })
        self.assertIn("at least one specific required_documents", response["error"])
        self.assertFalse(ctx.finished)

    @patch("backend.services.agent_tools.repo.save_transaction_result", side_effect=RuntimeError("database unavailable"))
    @patch("backend.services.agent_tools.repo.get_transaction_result", return_value=None)
    def test_database_failure_never_reports_a_saved_verification(self, _get_result, _save_result):
        tx = _phase_a_transactions(self.phase_a)[0]
        ctx = ToolContext("CASE1", [], chain={"transactions": [tx]}, current_tx_id=tx["tx_id"])
        dispatch(ctx, "record_evidence_requirements", {"requirements": [{
            "document_type": "Gift deed", "reason": "Verify the transfer.",
        }]})
        dispatch(ctx, "list_documents", {})
        response = dispatch(ctx, "save_transaction_result", {
            "tx_id": tx["tx_id"], "sequence": 1,
            "status": "PENDING_NOT_VERIFIED", "summary": "The deed remains unverified.",
            "required_documents": [{"document_type": "Gift deed", "reason": "Verify the transfer."}],
        })
        self.assertIn("error", response)
        self.assertNotIn("saved", response)
        self.assertIsNotNone(ctx.result_error)
        self.assertEqual(ctx.saved_results, [])

    @patch("backend.services.agent_tools.repo.get_transaction_result", return_value=None)
    def test_transaction_result_does_not_inherit_another_transactions_findings(self, _get_result):
        later = _phase_a_transactions(self.phase_a)[1]
        ctx = ToolContext("CASE1", [], chain={"transactions": [later]}, current_tx_id=later["tx_id"])
        result = _canonical_verification(ctx, {
            "tx_id": later["tx_id"], "sequence": 2,
            "status": "INCONCLUSIVE", "summary": "The later instrument is insufficiently supported.",
            "findings": [], "required_documents": [],
        })
        self.assertEqual(result["findings"], [])

    @patch("backend.services.agent_tools.repo.save_transaction_result")
    @patch("backend.services.agent_tools.repo.get_transaction_result", return_value=None)
    def test_invalid_output_is_rejected_without_persistence(self, get_result, save_result):
        tx = _phase_a_transactions(self.phase_a)[0]
        ctx = ToolContext("CASE1", [], chain={"transactions": [tx]}, current_tx_id=tx["tx_id"])
        response = dispatch(ctx, "save_transaction_result", {
            "tx_id": "PA-TC-0001", "sequence": 1, "status": "MADE_UP",
            "summary": "Unsupported status", "conclusion": "legacy alias",
        })
        self.assertIn("error", response)
        save_result.assert_not_called()

    @patch("backend.services.agent_tools.repo.save_transaction_result")
    @patch("backend.services.agent_tools.repo.get_transaction_result", return_value=None)
    def test_nested_finding_aliases_are_rejected_by_canonical_contract(self, get_result, save_result):
        tx = _phase_a_transactions(self.phase_a)[0]
        ctx = ToolContext("CASE1", [], chain={"transactions": [tx]}, current_tx_id=tx["tx_id"])
        response = dispatch(ctx, "save_transaction_result", {
            "tx_id": "PA-TC-0001", "sequence": 1,
            "status": "ISSUES_IDENTIFIED", "summary": "A discrepancy is documented.",
            "findings": [{"description": "Descriptions differ", "evidence": [{"doc_id": "DOC1"}]}],
        })
        self.assertIn("error", response)
        save_result.assert_not_called()

    @patch("backend.services.agent_tools.repo.save_transaction_result")
    @patch("backend.services.agent_tools.repo.get_transaction_result", return_value=None)
    def test_tool_schema_is_derived_from_canonical_result_contract(self, get_result, save_result):
        schema = next(tool for tool in tools_for("verify") if tool["name"] == "save_transaction_result")["parameters"]
        self.assertEqual(set(schema["properties"]), set(__import__(
            "backend.services.agent_schemas", fromlist=["TransactionVerification"]
        ).TransactionVerification.model_fields))
        self.assertTrue({"tx_id", "sequence", "status", "summary"}.issubset(set(schema["required"])))
        self.assertNotIn("missing_documents", schema["properties"])
        self.assertNotIn("conclusion", schema["properties"])

    @patch("backend.services.agent_tools.repo.save_transaction_result")
    @patch("backend.services.agent_tools.repo.get_transaction_result", return_value=None)
    def test_duplicate_outstanding_requirements_are_collapsed(self, get_result, save_result):
        tx = _phase_a_transactions(self.phase_a)[0]
        ctx = ToolContext("CASE1", [], chain={"transactions": [tx]}, current_tx_id=tx["tx_id"])
        requirement = {"document_type": "Sale deed", "reason": "Verify transfer"}
        dispatch(ctx, "record_evidence_requirements", {"requirements": [requirement]})
        dispatch(ctx, "list_documents", {})
        dispatch(ctx, "save_transaction_result", {
            "tx_id": "PA-TC-0001", "sequence": 1, "status": "PENDING_NOT_VERIFIED",
            "summary": "The transfer remains unverified.",
            "required_documents": [requirement, dict(requirement)],
        })
        self.assertEqual(len(save_result.call_args.kwargs["verification"]["required_documents"]), 1)

    @patch("backend.services.agent_tools.repo.get_transaction_result")
    def test_resume_preserves_prior_findings_evidence_and_reviewed_ids(self, get_result):
        tx = _phase_a_transactions(self.phase_a)[0]
        prior = {
            "tx_id": "PA-TC-0001", "sequence": 1, "status": "PENDING_NOT_VERIFIED",
            "summary": "Still awaiting primary evidence.",
            "findings": [{"description": "Later deed recites this transfer.", "source_refs": [{
                "doc_id": "DOC1", "page": "2", "passage": "A long copied OCR quote repeats the finding details."
            }]}],
            "supporting_evidence": [{"doc_id": "DOC1", "page": "2"}],
            "contradictory_evidence": [{"doc_id": "DOC2", "page": "4"}],
            "required_documents": [{"document_type": "Original deed", "reason": "Verify conveyance"}],
            "reviewed_document_ids": ["DOC1"],
        }
        get_result.return_value = prior
        ctx = ToolContext(
            "CASE1",
            [
                {"doc_id": "DOC1", "filename": "old-source.pdf"},
                {"doc_id": "DOC2", "filename": "old-conflict.pdf"},
            ],
            chain={"transactions": [tx]},
            current_tx_id=tx["tx_id"],
        )
        ctx.selected_document_ids.update({"DOC1", "DOC2"})
        ctx.read_text_ranges = {
            "DOC1": [(0, 10, 10)],
            "DOC2": [(0, 10, 10)],
        }

        result = _canonical_verification(ctx, {
            "tx_id": "PA-TC-0001", "sequence": 1, "status": "INCONCLUSIVE",
            "findings": [{
                "title": "Evidence finding",
                "details": "Later deed recites this transfer.",
                "evidence": [{"doc_id": "DOC1", "pages": "2"}],
            }, {
                "title": "Contradictory evidence",
                "details": "The conflicting record remains relevant.",
                "evidence": [{"doc_id": "DOC2", "pages": "4"}],
            }],
            "summary": "The records remain inconclusive after reviewing an additional record.",
            "required_documents": [],
        })

        self.assertEqual(result["findings"][0]["title"], "Evidence finding")
        self.assertIn("Later deed recites this transfer.", result["findings"][0]["details"])
        self.assertEqual(result["findings"][0]["evidence"][0]["pages"], "2")
        self.assertNotIn("passage", result["findings"][0]["evidence"][0])
        self.assertEqual(result["findings"][-1]["evidence"][0]["doc_id"], "DOC2")
        self.assertEqual(result["required_documents"], [])
        self.assertEqual(result["reviewed_document_ids"], ["DOC1", "DOC2"])
        self.assertIsNotNone(result["verified_at"])

    @patch("backend.services.agent_tools.repo.get_transaction_result")
    def test_fresh_reverification_does_not_load_or_merge_saved_active_result(self, get_result):
        tx = _phase_a_transactions(self.phase_a)[0]
        ctx = ToolContext(
            "CASE1", [], chain={"transactions": [tx]}, current_tx_id=tx["tx_id"],
            fresh_reverification=True,
        )
        result = _canonical_verification(ctx, {
            "tx_id": tx["tx_id"], "sequence": 1, "status": "INCONCLUSIVE",
            "summary": "A new review could not reach a reliable conclusion.",
            "findings": [], "required_documents": [],
        })

        get_result.assert_not_called()
        self.assertEqual(result["findings"], [])
        self.assertEqual(result["reviewed_document_ids"], [])
        self.assertEqual(result["required_documents"], [])

    @patch("backend.services.cleartitle_agent._sync_case_verdict")
    @patch("backend.services.cleartitle_agent._verify_transaction")
    @patch("backend.services.cleartitle_agent.ensure_summaries")
    @patch("backend.services.cleartitle_agent.repo")
    def test_run_verifies_pending_phase_a_entries_and_skips_completed(self, repo, ensure, verify, sync_verdict):
        repo.get_agent_documents.return_value = [{"doc_id": "DOC1"}]
        repo.get_agent_memory.return_value = {}
        repo.get_agent_result.return_value = self.phase_a
        repo.get_transaction_result.side_effect = [
            {"status": "VERIFIED_WITH_AVAILABLE_EVIDENCE"},
            {"status": "PENDING_NOT_VERIFIED"},
            {"status": "VERIFIED_WITH_AVAILABLE_EVIDENCE"},
        ]
        repo.list_transaction_results.return_value = [{"tx_id": "PA-TC-0002", "status": "PENDING_NOT_VERIFIED"}]
        verify.return_value = SimpleNamespace(missing_requests=[], saved_results=[{"status": "VERIFIED_WITH_AVAILABLE_EVIDENCE"}])

        outcome = _run("CASE1")

        self.assertEqual(outcome["status"], "done")
        self.assertEqual(verify.call_count, 1)
        self.assertEqual(verify.call_args.args[3]["tx_id"], "PA-TC-0002")
        self.assertEqual(verify.call_args.args[2], self.phase_a)
        repo.get_title_chain.assert_not_called()
        repo.save_agent_result.assert_not_called()

    @patch("backend.services.cleartitle_agent._sync_case_verdict")
    @patch("backend.services.cleartitle_agent._verify_transaction")
    @patch("backend.services.cleartitle_agent.ensure_summaries")
    @patch("backend.services.cleartitle_agent.repo")
    def test_fresh_run_reverifies_terminal_saved_transactions(self, repo, ensure, verify, sync_verdict):
        repo.get_agent_documents.return_value = [{"doc_id": "DOC1"}]
        repo.get_agent_memory.return_value = {}
        repo.get_agent_result.return_value = self.phase_a
        repo.get_transaction_result.return_value = {"status": "VERIFIED_WITH_AVAILABLE_EVIDENCE"}
        repo.list_transaction_results.return_value = [
            {"tx_id": "PA-TC-0001", "status": "VERIFIED_WITH_AVAILABLE_EVIDENCE"},
            {"tx_id": "PA-TC-0002", "status": "VERIFIED_WITH_AVAILABLE_EVIDENCE"},
        ]
        verify.return_value = SimpleNamespace(
            missing_requests=[],
            saved_results=[{"status": "VERIFIED_WITH_AVAILABLE_EVIDENCE"}],
        )

        outcome = _run("CASE1", fresh_reverification=True)

        self.assertEqual(outcome["status"], "done")
        self.assertEqual(verify.call_count, 2)
        self.assertTrue(all(call.kwargs.get("fresh_reverification") is True for call in verify.call_args_list))

    @patch("backend.services.cleartitle_agent._sync_case_verdict")
    @patch("backend.services.cleartitle_agent._verify_transaction")
    @patch("backend.services.cleartitle_agent.ensure_summaries")
    @patch("backend.services.cleartitle_agent.repo")
    def test_run_pauses_current_transaction_when_verifier_requests_missing_evidence(self, repo, ensure, verify, sync_verdict):
        repo.get_agent_documents.return_value = [{"doc_id": "DOC1"}]
        repo.get_agent_memory.return_value = {}
        repo.get_agent_result.return_value = self.phase_a
        repo.get_transaction_result.return_value = None
        verify.return_value = SimpleNamespace(missing_requests=[{
            "tx_id": "PA-TC-0001",
            "documents": [{"document_type": "Certified gift deed", "reason": "Confirm registered gift instrument"}],
        }])

        outcome = _run("CASE1")

        self.assertEqual(outcome["status"], "paused")
        self.assertEqual(outcome["paused_transaction"], "PA-TC-0001")
        self.assertEqual(verify.call_count, 1)
        self.assertEqual(outcome["missing_documents"][0]["document_type"], "Certified gift deed")

    @patch("backend.services.cleartitle_agent._run", return_value={"status": "done"})
    @patch("backend.services.cleartitle_agent.repo")
    def test_skipping_paused_transaction_preserves_result_and_continues(self, repo, run):
        repo.get_agent_result.return_value = self.phase_a
        repo.get_agent_memory.return_value = {
            "paused_transaction": "PA-TC-0002",
            "skipped_tx_ids": ["PA-TC-0001"],
            "pending_tx_ids": ["PA-TC-0001"],
        }
        prior = {
            "tx_id": "PA-TC-0002", "sequence": 2,
            "status": "PENDING_NOT_VERIFIED", "summary": "Succession is recital-reported.",
            "transaction_metadata": {"transaction_type": "Succession"},
            "required_documents": [{"document_type": "Death record", "reason": "Verify succession"}],
            "findings": [{"description": "Succession is recital-reported"}],
        }
        repo.get_transaction_result.return_value = prior

        outcome = _skip_transaction_locked("CASE1", "PA-TC-0002")

        self.assertEqual(outcome["status"], "done")
        repo.save_transaction_result.assert_not_called()
        self.assertEqual(repo.get_transaction_result.return_value, prior)
        saved_memory = repo.save_agent_memory.call_args.kwargs["memory"]
        self.assertEqual(saved_memory["skipped_tx_ids"], ["PA-TC-0001", "PA-TC-0002"])
        run.assert_called_once_with("CASE1", skip_tx_ids={"PA-TC-0001", "PA-TC-0002"})

    @patch("backend.services.cleartitle_agent.repo")
    def test_only_currently_paused_transaction_can_be_skipped(self, repo):
        repo.get_agent_result.return_value = self.phase_a
        repo.get_agent_memory.return_value = {"paused_transaction": "PA-TC-0002"}

        outcome = _skip_transaction_locked("CASE1", "PA-TC-0001")

        self.assertEqual(outcome["status"], "error")
        repo.save_transaction_result.assert_not_called()

    @patch("backend.services.cleartitle_agent.PIPELINE_LOCK_ENABLED", False)
    @patch("backend.services.cleartitle_agent._run", return_value={"status": "paused"})
    @patch("backend.services.cleartitle_agent.repo")
    def test_new_analysis_resume_retries_persistently_skipped_transactions(self, repo, run):
        repo.get_agent_memory.return_value = {"skipped_tx_ids": ["PA-TC-0001"]}

        _run_with_lock("CASE1")

        saved_memory = repo.save_agent_memory.call_args.kwargs["memory"]
        self.assertEqual(saved_memory["skipped_tx_ids"], [])
        run.assert_called_once_with("CASE1", skip_tx_ids=set())

    @patch("backend.services.cleartitle_agent.PIPELINE_LOCK_ENABLED", False)
    @patch("backend.services.cleartitle_agent._run", return_value={"status": "paused"})
    @patch("backend.services.cleartitle_agent.repo")
    def test_explicit_resume_preserves_skipped_transactions(self, repo, run):
        skipped = {"PA-TC-0001", "PA-TC-0002"}
        repo.get_agent_memory.return_value = {"skipped_tx_ids": sorted(skipped)}

        _run_with_lock("CASE1", skip_tx_ids=skipped)

        repo.save_agent_memory.assert_not_called()
        run.assert_called_once_with("CASE1", skip_tx_ids=skipped)

    @patch("backend.services.cleartitle_agent.PIPELINE_LOCK_ENABLED", False)
    @patch("backend.services.cleartitle_agent._run", return_value={"status": "done"})
    @patch("backend.services.cleartitle_agent.repo")
    def test_targeted_fresh_reverification_preserves_skip_memory(self, repo, run):
        repo.get_agent_memory.return_value = {"skipped_tx_ids": ["PA-TC-0003"]}
        selected = {"PA-TC-0001", "PA-TC-0002"}

        _run_with_lock("CASE1", fresh_reverification=True, transaction_ids=selected)

        repo.save_agent_memory.assert_not_called()
        run.assert_called_once_with(
            "CASE1", skip_tx_ids=None, fresh_reverification=True,
            transaction_ids=selected,
        )


if __name__ == "__main__":
    unittest.main()
