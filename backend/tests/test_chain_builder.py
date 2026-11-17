"""The title-chain builder: history documents first, deeds on the path, gates in code."""

import unittest
from unittest.mock import patch

from pydantic import ValidationError
from pydantic_ai import ModelResponse, ToolCallPart, capture_run_messages, models
from pydantic_ai.models.function import FunctionModel

from backend.schemas.chain import ChainResult
from backend.services import chain_builder, cleartitle_agent

models.ALLOW_MODEL_REQUESTS = False


def document(doc_id, filename, document_type, **extra):
    return {
        "doc_id": doc_id,
        "filename": filename,
        "document_type": document_type,
        "status": "structured",
        **extra,
    }


DEED = document("DOC_001", "deed.pdf", "SALE_DEED", summary="Sale deed REG-1 of 2010, A to B.")
EC = document("DOC_002", "ec.pdf", "ENCUMBRANCE_CERTIFICATE")
MUTATION = document("DOC_003", "mutation.pdf", "MUTATION")
RECEIPT = document("DOC_004", "tax.pdf", "TAX_RECEIPT")
DEED_1990 = document("DOC_005", "deed-1990.pdf", "SALE_DEED")
DEED_2012 = document("DOC_007", "deed-2012.pdf", "SALE_DEED")
PARTNERSHIP = document(
    "DOC_006", "partnership.pdf", "PARTNERSHIP_DEED", summary="Partnership deed."
)
PARTNERS = ("Shri Ravindra Shivaputra Chobari", "Shri Sachin Anant Bailwad")

READ_EC = [("read_document", {"doc_id": "DOC_002"})]
READ_DEED = [("read_document", {"doc_id": "DOC_001"})]
READ_DEED_1990 = [("read_document", {"doc_id": "DOC_005"})]
READ_DEED_2012 = [("read_document", {"doc_id": "DOC_007"})]
READ_PARTNERSHIP = [("read_document", {"doc_id": "DOC_006"})]


def ref(source):
    return {"doc_id": source["doc_id"], "filename": source["filename"]}


def link(
    position,
    *,
    number=None,
    kind="Sale",
    date=None,
    transferors=("A",),
    transferees=("B",),
    sources=(EC,),
    status="register_reported",
    continues=False,
    **extra,
):
    return {
        "chain_position": position,
        "continues_previous": continues,
        "documented_transaction": {
            "transaction_number": number,
            "transaction_type": kind,
            "executed_date": date,
            "transferors": list(transferors),
            "transferees": list(transferees),
            "summary_points": ["The property passed to the acquirer."],
            "source_refs": [ref(source) for source in sources],
            "evidence_status": status,
            **extra,
        },
    }


def chain(*links, **extra):
    return {
        "property_identity": {
            "details": [
                {"label": "Survey number", "value": "12/3", "source_refs": [ref(EC)]},
            ]
        },
        "title_chain": list(links),
        **extra,
    }


ONE_SALE = chain(link(1, number="REG-1"))


def scripted_model(*steps):
    """A model that plays ``steps`` in order, one per request.

    Each step is a list of ``(tool_name, args)`` calls; the name ``"result"``
    stands for the agent's final-result tool.
    """
    pending = list(steps)

    def respond(messages, info):
        calls = pending.pop(0)
        return ModelResponse(
            parts=[
                ToolCallPart(info.output_tools[0].name if name == "result" else name, args)
                for name, args in calls
            ]
        )

    return FunctionModel(respond)


def retry_prompts(messages):
    """The rejection messages sent back to the model during a run."""
    return [
        str(part.content)
        for message in messages
        for part in message.parts
        if part.part_kind == "tool-return" and part.outcome == "retried"
    ]


class ChainBuilderCase(unittest.TestCase):
    def build(
        self,
        steps,
        *,
        documents=(EC,),
        texts=None,
        prior_chain=(),
        prior_results=(),
        chain_error=None,
    ):
        """Run ``build_chain`` against a scripted model and patched persistence."""
        texts = texts or {
            "DOC_001": "deed text",
            "DOC_002": "ec text",
            "DOC_003": "mutation text",
        }
        model = steps if isinstance(steps, FunctionModel) else scripted_model(*steps)
        with (
            patch.object(chain_builder, "build_agent_model", return_value=model),
            patch.object(
                chain_builder.repo,
                "get_document_raw_text",
                side_effect=lambda case_id, doc_id: texts[doc_id],
            ) as self.read_text,
            patch.object(
                chain_builder.repo,
                "get_persisted_title_chain_entries",
                side_effect=chain_error,
                return_value=list(prior_chain),
            ),
            patch.object(
                chain_builder.repo,
                "list_persisted_transaction_results",
                return_value=list(prior_results),
            ),
            patch.object(chain_builder.repo, "save_phase_a_result") as self.save,
            capture_run_messages() as self.messages,
        ):
            return chain_builder.build_chain("CASE1", list(documents))

    def loaded_documents(self):
        return [call.args[1] for call in self.read_text.call_args_list]


class TestScope(ChainBuilderCase):
    def test_only_processed_history_documents_are_history(self):
        failed_ec = {**EC, "doc_id": "DOC_009", "status": "failed"}
        self.assertEqual(
            chain_builder.history_documents([DEED, EC, MUTATION, RECEIPT, failed_ec]),
            [EC, MUTATION],
        )

    def test_property_register_cards_are_not_shown_to_the_chain_builder(self):
        cards = [
            document(label, "x.pdf", label)
            for label in (
                "PROPERTY_REGISTER_CARD",
                "PROPERTY_CARD",
                "PROPERTY_REGISTER_EXTRACT",
                "PROPERTY_RECORD",
                "FORM_2_PROPERTY_RECORD",
            )
        ]
        rtc = document("DOC_010", "rtc.pdf", "RTC_PAHANI")
        self.assertEqual(
            chain_builder.history_documents([*cards, EC, MUTATION, rtc]), [EC, MUTATION, rtc]
        )
        self.assertEqual(chain_builder.title_deeds(cards), [])

    def test_only_processed_deeds_are_title_deeds(self):
        deeds = [
            document(label, "x.pdf", label)
            for label in ("SALE_DEED", "PARTITION_DEED", "RELEASE_DEED", "WILL")
        ]
        failed_deed = {**DEED, "doc_id": "DOC_008", "status": "failed"}
        self.assertEqual(
            chain_builder.title_deeds([*deeds, EC, MUTATION, RECEIPT, failed_deed]), deeds
        )

    def test_task_lists_history_documents_and_deeds_with_summaries(self):
        task = chain_builder._task([EC], [DEED])
        self.assertIn("# Skill: Build the title chain", task)
        self.assertIn("- DOC_002 | ENCUMBRANCE_CERTIFICATE | filename: ec.pdf", task)
        self.assertIn("- DOC_001 | SALE_DEED | filename: deed.pdf | summary: Sale deed REG-1", task)
        self.assertTrue(chain_builder._task([EC], []).endswith("None uploaded."))

    def test_other_documents_cannot_be_read_and_their_text_is_never_loaded(self):
        self.build(
            [[("read_document", {"doc_id": "DOC_004"})], READ_EC, [("result", ONE_SALE)]],
            documents=(EC, DEED, RECEIPT),
        )
        self.assertIn("not a history document or title deed", retry_prompts(self.messages)[0])
        self.assertEqual(self.loaded_documents(), ["DOC_002"])

    def test_a_case_without_history_documents_cannot_build_a_chain(self):
        with self.assertRaises(chain_builder.ChainBuildError):
            self.build([], documents=(DEED,))
        self.save.assert_not_called()


class TestReadGate(ChainBuilderCase):
    def test_result_is_rejected_until_every_history_document_is_read(self):
        self.build(
            [
                READ_EC,
                [("result", ONE_SALE)],
                [("read_document", {"doc_id": "DOC_003"})],
                [("result", ONE_SALE)],
            ],
            documents=(EC, MUTATION),
        )
        prompts = retry_prompts(self.messages)
        self.assertEqual(len(prompts), 1)
        self.assertIn("Not fully read: DOC_003", prompts[0])
        self.save.assert_called_once()

    def test_a_long_document_must_be_read_to_its_end(self):
        with patch.object(chain_builder, "_CHUNK_CHARS", 4):
            self.build(
                [READ_EC, [("result", ONE_SALE)], READ_EC, READ_EC, [("result", ONE_SALE)]],
                texts={"DOC_002": "0123456789"},
            )
        self.assertIn("Not fully read: DOC_002", retry_prompts(self.messages)[0])
        chunks = [
            part.content["text"]
            for message in self.messages
            for part in message.parts
            if part.part_kind == "tool-return"
            and part.tool_name == "read_document"
            and part.outcome == "success"
        ]
        self.assertEqual(chunks, ["0123", "4567", "89"])
        self.save.assert_called_once()

    def test_deeds_are_optional_and_stay_unread_when_not_needed(self):
        self.build([READ_EC, [("result", ONE_SALE)]], documents=(EC, DEED))
        self.assertEqual(retry_prompts(self.messages), [])
        self.assertEqual(self.loaded_documents(), ["DOC_002"])
        self.save.assert_called_once()


class TestCitationGate(ChainBuilderCase):
    def assert_rejected(self, bad_chain, expected, *, documents=(EC,), fix=()):
        """``bad_chain`` is rejected with ``expected``; after ``fix`` steps the good chain saves."""
        self.build(
            [READ_EC, [("result", bad_chain)], *fix, [("result", ONE_SALE)]],
            documents=documents,
        )
        self.assertIn(expected, retry_prompts(self.messages)[0])
        self.save.assert_called_once()
        self.assertEqual(
            self.save.call_args.kwargs["result"]["title_chain"][0]["tx_id"], "PA-TC-0001"
        )

    def test_citation_to_a_document_outside_the_two_lists_is_rejected(self):
        self.assert_rejected(
            chain(link(1, number="REG-1", sources=(RECEIPT,))),
            "not a history document or title deed",
            documents=(EC, RECEIPT),
        )

    def test_citation_filename_is_resolved_from_the_fully_read_document(self):
        wrong = chain(
            link(1, number="REG-1", sources=({"doc_id": "DOC_002", "filename": "other.pdf"},))
        )
        result = self.build([READ_EC, [("result", wrong)]])
        self.assertEqual(retry_prompts(self.messages), [])
        self.assertEqual(
            result["title_chain"][0]["documented_transaction"]["source_refs"], [ref(EC)]
        )
        self.save.assert_called_once()

    def test_wrong_filename_does_not_bypass_the_deed_read_gate(self):
        wrong_deed = {**DEED, "filename": EC["filename"]}
        self.assert_rejected(
            chain(link(1, sources=(wrong_deed,), status="deed_reported")),
            "Read DOC_001 to the end before citing it",
            documents=(EC, DEED),
        )

    def test_missing_stored_filename_prevents_saving(self):
        with self.assertRaisesRegex(chain_builder.ChainBuildError, "no valid stored filename"):
            self.build([READ_EC, [("result", ONE_SALE)]], documents=({**EC, "filename": ""},))
        self.save.assert_not_called()

    def test_citing_a_deed_that_was_not_read_is_rejected(self):
        self.assert_rejected(
            chain(link(1, number="REG-1", sources=(EC, DEED), status="corroborated")),
            "Read DOC_001 to the end before citing it",
            documents=(EC, DEED),
        )

    def test_duplicate_registration_numbers_are_rejected(self):
        self.assert_rejected(
            chain(link(1, number="REG-1"), link(2, number="reg-1")), "duplicate transaction_number"
        )

    def test_a_model_supplied_transaction_id_is_rejected(self):
        self.assert_rejected(chain(link(1, number="REG-1", tx_id="PA-TC-0099")), "tx_id")


class TestEvidenceStatus(ChainBuilderCase):
    def assert_status_rejected(self, sources, status, expected):
        self.build(
            [
                [*READ_EC, *READ_DEED],
                [("result", chain(link(1, number="REG-1", sources=sources, status=status)))],
                [("result", ONE_SALE)],
            ],
            documents=(EC, DEED),
        )
        self.assertIn(expected, retry_prompts(self.messages)[0])

    def test_corroborated_needs_two_documents(self):
        self.assert_status_rejected((EC,), "corroborated", "two or more source documents")

    def test_register_reported_needs_a_history_document(self):
        self.assert_status_rejected((DEED,), "register_reported", "needs a history document")

    def test_recital_and_deed_reported_need_a_title_deed(self):
        for status in ("recital_reported", "deed_reported"):
            self.assert_status_rejected((EC,), status, f"{status} needs a title deed")

    def test_a_link_known_only_from_a_deed_recital_extends_the_chain_backward(self):
        extended = chain(
            link(1, kind="Partition", sources=(DEED,), status="recital_reported"),
            link(2, number="REG-1", sources=(EC, DEED), status="corroborated", continues=True),
        )
        result = self.build([[*READ_EC, *READ_DEED], [("result", extended)]], documents=(EC, DEED))
        self.assertEqual(retry_prompts(self.messages), [])
        self.assertEqual(
            [entry["documented_transaction"]["evidence_status"] for entry in result["title_chain"]],
            ["recital_reported", "corroborated"],
        )


    def test_later_deed_recital_can_bridge_an_internal_succession_gap(self):
        connected = chain(
            link(1, number="REG-2010", date="01-01-2010", transferees=("B",)),
            link(
                2, kind="Succession", transferors=("B",), transferees=("C", "D"),
                sources=(DEED,), status="recital_reported", continues=True,
                summary_points=["The later sale deed states that C and D inherited B's property."],
            ),
            link(
                3, number="REG-2019", date="01-01-2019", transferors=("C", "D"),
                transferees=("E",), continues=True,
            ),
        )
        result = self.build(
            [READ_EC, READ_DEED, [("result", connected)]],
            documents=(EC, DEED),
            texts={
                "DOC_002": "2010: A sold to B. 2019: C and D sold to E.",
                "DOC_001": "C and D inherited this property from B and now sell it to E.",
            },
        )
        self.assertEqual(self.loaded_documents(), ["DOC_002", "DOC_001"])
        self.assertNotIn("No recorded transfer", result["title_chain_graph"])
        self.assertEqual(result["missing_documents"], [])
        self.assertEqual(
            result["title_chain"][1]["documented_transaction"]["source_refs"], [ref(DEED)]
        )


class TestContinuity(ChainBuilderCase):
    def test_a_partition_recital_must_be_placed_before_the_sale_it_precedes(self):
        misordered = chain(
            link(
                1,
                number="1415/1990-91",
                date="18-08-1990",
                transferors=("Mrs. Meena P. Kulkarni",),
                transferees=("Shri Anant Dattatraya Mankikar",),
            ),
            link(
                2,
                kind="Partition",
                transferors=("Smt. Meena w/o Prakash Kulkarni", "Smt. Sharmila w/o Vinod Dixit"),
                transferees=("Smt. Meena w/o Prakash Kulkarni",),
                continues=True,
            ),
        )
        ordered = chain(
            link(
                1,
                kind="Partition",
                transferors=("Smt. Meena w/o Prakash Kulkarni", "Smt. Sharmila w/o Vinod Dixit"),
                transferees=("Smt. Meena w/o Prakash Kulkarni",),
                sources=(DEED_2012,),
                status="recital_reported",
            ),
            link(
                2,
                number="1415/1990-91",
                date="18-08-1990",
                transferors=("Mrs. Meena P. Kulkarni",),
                transferees=("Shri Anant Dattatraya Mankikar",),
                continues=True,
            ),
        )
        result = self.build(
            [READ_EC, READ_DEED_2012, [("result", misordered)], [("result", ordered)]],
            documents=(EC, DEED_2012),
            texts={"DOC_002": "ec text", "DOC_007": "partition recital text"},
        )
        prompt = retry_prompts(self.messages)[0]
        self.assertIn("are not link 1's acquirers", prompt)
        self.assertIn("put it before the transfer it precedes", prompt)
        self.assertEqual(
            [
                entry["documented_transaction"]["transaction_type"]
                for entry in result["title_chain"]
            ],
            ["Partition", "Sale"],
        )
        self.save.assert_called_once()

    def test_an_entity_cannot_continue_owners_it_does_not_name(self):
        unsupported = chain(
            link(
                1,
                number="REG-1",
                transferors=("Meena Kulkarni",),
                transferees=("Anant Mankikar",),
            ),
            link(
                2,
                number="REG-2",
                transferors=("Sapthagiri Associates",),
                transferees=("Chandrashekhar Hadimani",),
                continues=True,
            ),
        )
        gapped = chain(
            link(
                1,
                number="REG-1",
                transferors=("Meena Kulkarni",),
                transferees=("Anant Mankikar",),
            ),
            link(
                2,
                number="REG-2",
                transferors=("Sapthagiri Associates",),
                transferees=("Chandrashekhar Hadimani",),
                continues=False,
            ),
        )
        result = self.build([READ_EC, [("result", unsupported)], [("result", gapped)]])
        self.assertIn("are not link 1's acquirers", retry_prompts(self.messages)[0])
        self.assertIn("No recorded transfer", result["title_chain_graph"])
        self.save.assert_called_once()

    def test_the_first_link_cannot_continue_a_previous_transfer(self):
        bad = chain(link(1, number="REG-1", continues=True))
        result = self.build([READ_EC, [("result", bad)], [("result", ONE_SALE)]])
        self.assertIn("Link 1 is the earliest transfer", retry_prompts(self.messages)[0])
        self.assertFalse(result["title_chain"][0]["continues_previous"])
        self.save.assert_called_once()

    def test_ocr_name_variants_of_the_same_party_still_continue(self):
        connected = chain(
            link(
                1,
                number="REG-1",
                date="01-01-1990",
                transferors=("Sharmila Dixit",),
                transferees=("Smt. Meena w/o Prakash Kulkarni",),
            ),
            link(
                2,
                number="REG-2",
                date="01-01-2000",
                transferors=("Mrs. Meena P. Kulkarni",),
                transferees=("Anant Mankikar",),
                continues=True,
            ),
        )
        self.build([READ_EC, [("result", connected)]])
        self.assertEqual(retry_prompts(self.messages), [])
        self.save.assert_called_once()


class TestPartitionRecital(ChainBuilderCase):
    PARTITION_TEXT = (
        "By partition dated 23-12-1988 the southern half was allotted to "
        "Smt. Meena w/o Prakash Kulkarni under mutation entry 4930."
    )

    def reported(self):
        return chain(
            link(
                1,
                number="1415/1990-91",
                date="18-08-1990",
                transferors=("Smt. Meena w/o Prakash Kulkarni",),
                transferees=("Shri Anant Dattatraya Mankikar",),
                summary_points=[
                    "Meena sold the southern half to Anant.",
                    "The deed reports a partition of the property under mutation entry 4930.",
                ],
            )
        )

    def with_partition(self):
        return chain(
            link(
                1,
                kind="Partition",
                transferors=("Smt. Meena w/o Prakash Kulkarni", "Smt. Sharmila w/o Vinod Dixit"),
                transferees=("Smt. Meena w/o Prakash Kulkarni",),
                sources=(DEED_2012,),
                status="recital_reported",
                summary_points=["The 2012 deed recites the partition of the property."],
            ),
            link(
                2,
                number="1415/1990-91",
                date="18-08-1990",
                transferors=("Smt. Meena w/o Prakash Kulkarni",),
                transferees=("Shri Anant Dattatraya Mankikar",),
                continues=True,
            ),
        )

    def test_a_partition_reported_in_a_summary_must_be_a_link(self):
        result = self.build(
            [
                READ_EC,
                READ_DEED_2012,
                [("result", self.reported())],
                [("result", self.with_partition())],
            ],
            documents=(EC, DEED_2012),
            texts={"DOC_002": "ec text", "DOC_007": self.PARTITION_TEXT},
        )
        prompt = retry_prompts(self.messages)[0]
        self.assertIn("no Partition link", prompt)
        self.assertIn("23-12-1988", prompt)
        self.assertIn("DOC_007", prompt)
        self.assertEqual(
            [
                entry["documented_transaction"]["transaction_type"]
                for entry in result["title_chain"]
            ],
            ["Partition", "Sale"],
        )
        self.save.assert_called_once()

    def test_a_partition_claim_without_a_supporting_passage_is_not_retried(self):
        self.build(
            [READ_EC, [("result", self.reported())]],
            documents=(EC,),
        )
        self.assertEqual(retry_prompts(self.messages), [])
        self.save.assert_called_once()


class TestGapEvidence(ChainBuilderCase):
    """A reported gap is challenged once with the passages that may close it."""

    OCR_TEXT = (
        "Sale deed 1415/1990-91 dated 18-08-1990. Meena Prakash Tulkarni sold the "
        "southern half to Shrinath Battal alias Larkib. Signature block: P.A. holder "
        "of A.D. Mankikar. Registration endorsement of 1415/1990-91."
    )
    RECITAL_TEXT = (
        "Anant Dattatraya Mankikar purchased the southern half of Plot 40 under "
        "document 1415/1990-91 dated 18-08-1990 from Meena Prakash Tulkarni. "
        "By partition dated 23-12-1988 the southern half was allotted to Meena "
        "Prakash Tulkarni under mutation entry 4930."
    )

    def texts(self, recital=None):
        return {
            "DOC_002": "ec text",
            "DOC_005": self.OCR_TEXT,
            "DOC_007": recital or self.RECITAL_TEXT,
        }

    def wrong_chain(self):
        return chain(
            link(
                1,
                number="1415/1990-91",
                date="18-08-1990",
                transferors=("Mrs. Meena Prakash Tulkarni",),
                transferees=("Shrinath Battal alias Larkib",),
                sources=(DEED_1990,),
                status="deed_reported",
            ),
            link(
                2,
                number="7403/2009-10",
                date="15-12-2009",
                transferors=("Shri Anant Dattatraya Mankikar",),
                transferees=("Shri Ankur Laxmanbhai Patel",),
                sources=(DEED_2012,),
                status="recital_reported",
            ),
        )

    def reconciled_chain(self):
        return chain(
            link(
                1,
                kind="Partition",
                date="23-12-1988",
                transferors=("Smt. Sharmila",),
                transferees=("Smt. Meena Prakash Tulkarni",),
                sources=(DEED_2012,),
                status="recital_reported",
            ),
            link(
                2,
                number="1415/1990-91",
                date="18-08-1990",
                transferors=("Smt. Meena Prakash Tulkarni",),
                transferees=("Shri Anant Dattatraya Mankikar",),
                sources=(DEED_1990, DEED_2012),
                status="corroborated",
                continues=True,
            ),
            link(
                3,
                number="7403/2009-10",
                date="15-12-2009",
                transferors=("Shri Anant Dattatraya Mankikar",),
                transferees=("Shri Ankur Laxmanbhai Patel",),
                sources=(DEED_2012,),
                status="recital_reported",
                continues=True,
            ),
        )

    def read_steps(self):
        return [*READ_EC, *READ_DEED_1990, *READ_DEED_2012]

    def test_a_gap_between_ocr_conflicting_names_is_sent_back_with_the_evidence(self):
        result = self.build(
            [
                self.read_steps(),
                [("result", self.wrong_chain())],
                [("result", self.reconciled_chain())],
            ],
            documents=(EC, DEED_1990, DEED_2012),
            texts=self.texts(),
        )
        prompts = retry_prompts(self.messages)
        self.assertEqual(len(prompts), 1)
        self.assertIn("Anant Dattatraya Mankikar", prompts[0])
        self.assertIn("P.A. holder of A.D. Mankikar", prompts[0])
        self.assertIn("23-12-1988", prompts[0])
        self.assertIn("DOC_007", prompts[0])
        self.assertEqual(
            [entry["documented_transaction"]["transferees"] for entry in result["title_chain"]],
            [
                ["Smt. Meena Prakash Tulkarni"],
                ["Shri Anant Dattatraya Mankikar"],
                ["Shri Ankur Laxmanbhai Patel"],
            ],
        )
        self.assertNotIn("No recorded transfer", result["title_chain_graph"])
        self.save.assert_called_once()

    def test_resubmitting_the_same_gap_after_the_evidence_is_accepted(self):
        result = self.build(
            [
                self.read_steps(),
                [("result", self.wrong_chain())],
                [("result", self.wrong_chain())],
            ],
            documents=(EC, DEED_1990, DEED_2012),
            texts=self.texts(),
        )
        self.assertEqual(len(retry_prompts(self.messages)), 1)
        self.assertFalse(result["title_chain"][1]["continues_previous"])
        self.assertIn("No recorded transfer", result["title_chain_graph"])
        self.save.assert_called_once()

    def test_a_single_entity_word_does_not_surface_gap_evidence(self):
        text = "SAPTHAGIRI ASSOCIATES sold under sale deed 6716/2012-13."
        self.assertEqual(
            chain_builder._identity_passages(text, {"sapthagiri"}, {"6716", "2012"}, 3),
            [],
        )

    def test_the_earlier_deeds_own_mention_of_the_later_transferor_is_surfaced(self):
        text = "x" * 500 + " P.A. holder of A.D. Mankikar. " + "y" * 500
        passages = chain_builder._name_passages(text, {"mankikar"}, 2)
        self.assertEqual(len(passages), 1)
        self.assertIn("P.A. holder of A.D. Mankikar", passages[0])

    def test_a_gap_without_reconciling_passages_is_saved_without_a_retry(self):
        filler = "The deed records other property details. " * 40
        result = self.build(
            [
                self.read_steps(),
                [("result", self.wrong_chain())],
            ],
            documents=(EC, DEED_1990, DEED_2012),
            texts={
                "DOC_002": "ec text",
                "DOC_005": "Sale deed 1415/1990-91. Meena Prakash Tulkarni sold to Shrinath.",
                "DOC_007": (
                    "Sale deed 7403/2009-10. "
                    f"{filler} Anant Dattatraya Mankikar sold the property to Ankur."
                ),
            },
        )
        self.assertEqual(retry_prompts(self.messages), [])
        self.assertIn("No recorded transfer", result["title_chain_graph"])
        self.save.assert_called_once()


class TestEntityGap(ChainBuilderCase):
    """A firm name is the same owners only when its constitution says so."""

    def texts(self):
        return {
            "DOC_002": "ec text",
            "DOC_007": "deed text",
            "DOC_006": (
                "Partnership deed dated 05-02-2013 of SAPTHAGIRI ASSOCIATES. "
                "Partners: Ravindra Shivaputra Chobari and Sachin Anant Bailwad."
            ),
        }

    def entity_chain(self, continues=False):
        return chain(
            link(
                1,
                number="6716/2012-13",
                transferors=("Mr. Sebastian Balku D'Souza",),
                transferees=PARTNERS,
                sources=(DEED_2012,),
                status="deed_reported",
            ),
            link(
                2,
                number="BEL-1-09762-2015-16",
                transferors=("M/S. SAPTHAGIRI ASSOCIATES",),
                transferees=("Shri. Chandrashekhar S. Hadimani",),
                sources=(DEED_2012,),
                status="deed_reported",
                continues=continues,
            ),
        )

    def test_an_entity_gap_is_sent_back_to_read_the_constitution(self):
        result = self.build(
            [
                [*READ_EC, *READ_DEED_2012],
                [("result", self.entity_chain())],
                READ_PARTNERSHIP,
                [("result", self.entity_chain(continues=True))],
            ],
            documents=(EC, DEED_2012, PARTNERSHIP),
            texts=self.texts(),
        )
        prompts = retry_prompts(self.messages)
        self.assertEqual(len(prompts), 1)
        self.assertIn("DOC_006 (PARTNERSHIP_DEED)", prompts[0])
        self.assertIn("partners", prompts[0])
        self.assertTrue(result["title_chain"][1]["continues_previous"])
        self.assertNotIn("No recorded transfer", result["title_chain_graph"])
        self.save.assert_called_once()

    def test_entity_continuity_without_the_constitution_is_rejected(self):
        result = self.build(
            [
                [*READ_EC, *READ_DEED_2012],
                [("result", self.entity_chain(continues=True))],
                [("result", self.entity_chain())],
            ],
            documents=(EC, DEED_2012),
            texts={"DOC_002": "ec text", "DOC_007": "deed text"},
        )
        prompts = retry_prompts(self.messages)
        self.assertEqual(len(prompts), 1)
        self.assertIn("are not link 1's acquirers", prompts[0])
        self.assertFalse(result["title_chain"][1]["continues_previous"])
        self.save.assert_called_once()


class TestChainContract(unittest.TestCase):
    def test_empty_requests_misplaced_on_a_link_are_removed(self):
        entry = {**link(1), "missing_documents": []}
        result = ChainResult.model_validate(chain(entry)).model_dump()
        self.assertNotIn("missing_documents", result["title_chain"][0])
        self.assertEqual(result["missing_documents"], [])

    def test_nonempty_requests_misplaced_on_a_link_are_rejected(self):
        entry = {
            **link(1),
            "missing_documents": [{"document": "Sale deed", "reason": "Confirm EC."}],
        }
        with self.assertRaises(ValidationError):
            ChainResult.model_validate(chain(entry))

    def test_empty_requests_nested_in_a_transaction_are_removed(self):
        entry = link(1)
        entry["documented_transaction"] = {
            **entry["documented_transaction"],
            "missing_documents": [],
        }
        result = ChainResult.model_validate(chain(entry)).model_dump()
        self.assertNotIn(
            "missing_documents", result["title_chain"][0]["documented_transaction"]
        )

    def test_nonempty_requests_nested_in_a_transaction_are_rejected(self):
        entry = link(1)
        entry["documented_transaction"] = {
            **entry["documented_transaction"],
            "missing_documents": [{"document": "Sale deed", "reason": "Confirm EC."}],
        }
        with self.assertRaises(ValidationError):
            ChainResult.model_validate(chain(entry))

    def test_positions_must_run_from_one_without_gaps(self):
        with self.assertRaises(ValidationError):
            ChainResult.model_validate(chain(link(1, number="REG-1"), link(3, number="REG-2")))

    def test_a_link_needs_summary_points_and_a_source(self):
        for field in ("summary_points", "source_refs"):
            broken = link(1, number="REG-1")
            broken["documented_transaction"][field] = []
            with self.assertRaises(ValidationError):
                ChainResult.model_validate(chain(broken))

    def test_an_empty_chain_is_rejected(self):
        with self.assertRaises(ValidationError):
            ChainResult.model_validate(chain())

    def test_a_link_must_name_who_acquired_the_property(self):
        with self.assertRaises(ValidationError):
            ChainResult.model_validate(chain(link(1, number="REG-1", transferees=())))

    def test_links_must_run_in_date_order(self):
        late_first = chain(
            link(1, number="REG-1", date="04-10-2024"),
            link(2, number="REG-2", date="9 June 2008"),
        )
        with self.assertRaisesRegex(ValidationError, "link 2 is dated before link 1"):
            ChainResult.model_validate(late_first)

    def test_undated_and_partly_dated_links_do_not_block_the_order_check(self):
        ChainResult.model_validate(
            chain(
                link(1, number="REG-1", date="21-07-2010"),
                link(2, kind="Succession", date=None),
                link(3, number="REG-3", date="June 2019 (day left blank)"),
                link(4, number="REG-4", date="2024-10-04"),
            )
        )

    def test_the_order_check_uses_the_registration_date_when_no_execution_date_is_given(self):
        late_first = chain(
            link(1, number="REG-1", registration_date="04-10-2024"),
            link(2, number="REG-2", registration_date="21-07-2010"),
        )
        with self.assertRaisesRegex(ValidationError, "link 2 is dated before link 1"):
            ChainResult.model_validate(late_first)

    def test_a_mortgage_or_lease_can_never_be_a_chain_link(self):
        for label in ("Mortgage", "Deposit of title deeds", "Sale agreement", "Lease"):
            with self.assertRaisesRegex(ValidationError, "not an ownership transfer"):
                ChainResult.model_validate(chain(link(1, kind=label)))

    def test_a_release_deed_between_owners_is_still_a_transfer(self):
        ChainResult.model_validate(chain(link(1, kind="Release")))

    def test_events_nested_inside_a_transaction_are_moved_to_the_link(self):
        event = {
            "type": "Mortgage",
            "summary_points": ["The owner deposited the title deeds with a bank."],
            "source_refs": [ref(EC)],
        }
        nested = link(1, number="REG-1", related_events=[event])
        result = ChainResult.model_validate(chain(nested)).model_dump()
        self.assertEqual(result["title_chain"][0]["related_events"], [event])
        self.assertNotIn("related_events", result["title_chain"][0]["documented_transaction"])

    def test_a_graph_written_by_the_model_is_rejected(self):
        with self.assertRaises(ValidationError):
            ChainResult.model_validate({**ONE_SALE, "title_chain_graph": "A -> B"})


def dumped_links(*links):
    """Chain links as the builder sees them: validated, then dumped to plain dicts."""
    return ChainResult.model_validate(chain(*links)).model_dump()["title_chain"]


class TestChainGraph(unittest.TestCase):
    def test_graph_runs_from_the_earliest_owner_to_the_current_owner(self):
        links = dumped_links(
            link(1, number="REG-1", date="21-07-2010", transferors=["A"], transferees=["B"]),
            link(2, number="REG-2", transferors=["B"], transferees=["C", "D"], continues=True),
        )
        self.assertEqual(
            chain_builder.chain_graph(links).splitlines(),
            [
                "A",
                "        │",
                "        │ Sale — 21-07-2010 / REG-1",
                "        ▼",
                "B",
                "        │",
                "        │ Sale — REG-2",
                "        ▼",
                "C, D",
            ],
        )

    def test_a_gap_in_the_records_is_drawn_as_a_break_not_a_transfer(self):
        links = dumped_links(
            link(1, number="REG-1", transferors=["A"], transferees=["B"]),
            link(2, kind="Succession", transferors=[], transferees=["X"]),
        )
        graph = chain_builder.chain_graph(links).splitlines()
        self.assertEqual(
            graph[4:9],
            [
                "B",
                "        ┆",
                "        ┆ No recorded transfer connects these owners",
                "        ┆",
                "Earlier owner not recorded",
            ],
        )
        self.assertEqual(graph[-3:], ["        │ Succession", "        ▼", "X"])


class TestIdentityAndSave(ChainBuilderCase):
    TWO_SALES = chain(
        link(1, number="REG-1", transferors=["A"], transferees=["B"]),
        link(2, number="REG-2", transferors=["B"], transferees=["C"]),
    )

    def test_save_stamps_ids_upstream_links_and_the_documents_offered(self):
        result = self.build(
            [[*READ_EC, ("read_document", {"doc_id": "DOC_003"})], [("result", self.TWO_SALES)]],
            documents=(MUTATION, EC, DEED, RECEIPT),
        )
        first, second = result["title_chain"]
        self.assertEqual([first["tx_id"], second["tx_id"]], ["PA-TC-0001", "PA-TC-0002"])
        self.assertIsNone(first.get("upstream_tx_ids"))
        self.assertEqual(second["upstream_tx_ids"], ["PA-TC-0001"])
        self.save.assert_called_once_with(
            case_id="CASE1", result=result, chain_doc_ids=["DOC_001", "DOC_002", "DOC_003"]
        )

    def test_chain_document_requests_are_rejected_before_saving(self):
        request = {"document": "EC for 1994 to 2010", "reason": "Shows how A got the property."}
        requested = chain(link(1, number="REG-1"), missing_documents=[request])
        with self.assertRaises(ValidationError):
            ChainResult.model_validate(requested)
        result = self.build(
            [READ_EC, [("result", requested)], [("result", ONE_SALE)]]
        )
        self.assertEqual(result["missing_documents"], [])
        self.save.assert_called_once()
        self.assertEqual(self.save.call_args.kwargs["result"]["missing_documents"], [])

    def test_a_rebuild_keeps_the_ids_of_links_it_matches(self):
        prior = [
            {
                "chain_position": 1,
                "tx_id": "PA-TC-0001",
                "documented_transaction": {
                    "transaction_type": "Sale",
                    "transaction_number": "REG-2",
                },
            }
        ]
        result = self.build([READ_EC, [("result", self.TWO_SALES)]], prior_chain=prior)
        self.assertEqual(
            [entry["tx_id"] for entry in result["title_chain"]], ["PA-TC-0002", "PA-TC-0001"]
        )

    def test_an_id_held_by_a_saved_result_is_never_given_to_another_transaction(self):
        prior_results = [{"tx_id": "PA-TC-0001"}, {"tx_id": "PA-TC-0003"}]
        result = self.build([READ_EC, [("result", self.TWO_SALES)]], prior_results=prior_results)
        self.assertEqual(
            [entry["tx_id"] for entry in result["title_chain"]], ["PA-TC-0002", "PA-TC-0004"]
        )

    def test_an_unreadable_identity_history_aborts_without_saving(self):
        with self.assertRaises(chain_builder.ChainBuildError) as raised:
            self.build([READ_EC, [("result", ONE_SALE)]], chain_error=RuntimeError("db down"))
        self.assertIn("nothing was saved", str(raised.exception))
        self.save.assert_not_called()

    def test_an_exhausted_call_budget_fails_without_saving(self):
        always_reading = FunctionModel(
            lambda messages, info: ModelResponse(
                parts=[ToolCallPart("read_document", {"doc_id": "DOC_002"})]
            )
        )
        with (
            patch.object(chain_builder, "CLEARTITLE_CHAIN_MODEL_CALL_BUDGET", 3),
            self.assertRaises(chain_builder.ChainBuildError),
        ):
            self.build(always_reading)
        self.save.assert_not_called()


def saved_chain(chain_doc_ids=("DOC_001", "DOC_002")):
    """A saved one-link chain and the documents it was built from."""
    return {
        "title_chain": [
            {
                "chain_position": 1,
                "tx_id": "PA-TC-0001",
                "documented_transaction": {"transaction_type": "Sale"},
            }
        ],
        "chain_doc_ids": None if chain_doc_ids is None else list(chain_doc_ids),
    }


class TestOrchestration(unittest.TestCase):
    def run_agent(self, *, documents, stored, transaction_ids=None):
        terminal = {
            "tx_id": "PA-TC-0001",
            "status": "VERIFIED_WITH_AVAILABLE_EVIDENCE",
            "report": "ok",
        }
        with (
            patch.object(cleartitle_agent.repo, "get_agent_documents", return_value=documents),
            patch.object(cleartitle_agent.repo, "get_agent_memory", return_value={}),
            patch.object(cleartitle_agent.repo, "get_agent_result", return_value=stored),
            patch.object(cleartitle_agent.repo, "set_agent_status"),
            patch.object(
                cleartitle_agent.repo,
                "list_transaction_results",
                return_value=[terminal] if stored else [],
            ),
            patch.object(cleartitle_agent.repo, "get_transaction_result", return_value=terminal),
            patch.object(
                cleartitle_agent.repo, "resequence_transaction_results"
            ) as self.resequence,
            patch.object(cleartitle_agent, "_save_state") as self.save_state,
            patch.object(cleartitle_agent, "_sync_case_verdict"),
            patch.object(cleartitle_agent, "ensure_summaries"),
            patch.object(
                cleartitle_agent, "build_chain", return_value=saved_chain()
            ) as self.build_chain,
        ):
            return cleartitle_agent._run("CASE1", transaction_ids=transaction_ids)

    def test_no_history_documents_pauses_and_asks_for_the_ec(self):
        outcome = self.run_agent(documents=[DEED], stored={})
        self.build_chain.assert_not_called()
        self.assertEqual(outcome["status"], cleartitle_agent.STATUS_PAUSED)
        self.assertEqual(
            outcome["missing_documents"][0]["document_type"], "Encumbrance Certificate"
        )
        memory, status = self.save_state.call_args.args[1:]
        self.assertEqual(memory["stage"], "awaiting_history_documents")
        self.assertIn("Encumbrance Certificate", memory["next_action"])
        self.assertEqual(status, cleartitle_agent.STATUS_PAUSED)

    def test_the_builder_is_given_the_case_documents_once_a_history_document_exists(self):
        self.run_agent(documents=[DEED, EC, RECEIPT], stored={})
        self.build_chain.assert_called_once_with("CASE1", [DEED, EC, RECEIPT])

    def test_a_new_history_document_rebuilds_the_chain_and_renumbers_results(self):
        outcome = self.run_agent(documents=[DEED, EC, MUTATION], stored=saved_chain())
        self.build_chain.assert_called_once_with("CASE1", [DEED, EC, MUTATION])
        self.resequence.assert_called_once_with(case_id="CASE1", sequences={"PA-TC-0001": 1})
        self.assertEqual(outcome["status"], cleartitle_agent.STATUS_DONE)

    def test_a_new_title_deed_rebuilds_the_chain(self):
        older_deed = document("DOC_007", "deed-2007.pdf", "SALE_DEED")
        self.run_agent(documents=[DEED, EC, older_deed], stored=saved_chain())
        self.build_chain.assert_called_once()

    def test_a_new_document_outside_the_chain_scope_does_not_rebuild(self):
        self.run_agent(documents=[DEED, EC, RECEIPT], stored=saved_chain())
        self.build_chain.assert_not_called()

    def test_a_scoped_run_never_rebuilds_the_chain(self):
        self.run_agent(
            documents=[DEED, EC, MUTATION],
            stored=saved_chain(),
            transaction_ids={"PA-TC-0001"},
        )
        self.build_chain.assert_not_called()

    def test_a_chain_saved_before_source_tracking_is_never_rebuilt_automatically(self):
        legacy = saved_chain(chain_doc_ids=None)
        self.run_agent(documents=[DEED, EC, MUTATION], stored=legacy)
        self.build_chain.assert_not_called()


if __name__ == "__main__":
    unittest.main()
