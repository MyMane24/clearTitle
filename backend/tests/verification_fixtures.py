"""Shared test data for the verification agent: a small case with three transfers."""

from backend.services.verification import case_file as cf

EC_TEXT = (
    "--- Page 1 ---\nEncumbrance Certificate for Sy.No.45, Hosahalli village.\n"
    "--- Page 2 ---\n2005: Partition deed among Basavaraj, Bhimappa and Bharathi.\n"
    "2012: Mortgage by Chandrashekar to Canara Bank.\n"
)
DEED_1998_TEXT = (
    "--- Page 1 ---\nSale deed No. 1234/1998. Vendor: Anand Rao. Purchaser: Basavaraj.\n"
    "--- Page 2 ---\nSchedule: Sy.No.45, extent 2 acres 10 guntas, Hosahalli.\n"
)
DEED_2010_TEXT = (
    "--- Page 1 ---\nSale deed No. 555/2010. Vendors: Basavaraj and Bhimesh (minor, "
    "represented by guardian Basavaraj). Purchaser: Chandrashekar.\n"
    "--- Page 2 ---\nThe vendor acquired the property under the partition of 2005, "
    "Schedule B.\n"
)
DEED_2018_TEXT = (
    "--- Page 1 ---\nSale deed No. 777/2018. Vendor: Chandrashekar. Purchaser: Deepa.\n"
    "--- Page 2 ---\nStamp duty paid Rs. 1,20,000.\n"
)

TEXTS = {
    "EC": EC_TEXT,
    "D1998": DEED_1998_TEXT,
    "D2010": DEED_2010_TEXT,
    "D2018": DEED_2018_TEXT,
}


def document(doc_id, filename, document_type, status="structured"):
    return {
        "doc_id": doc_id,
        "filename": filename,
        "document_type": document_type,
        "status": status,
        "summary": f"{document_type} {filename}",
    }


DOCUMENTS = [
    document("EC", "ec.pdf", "ENCUMBRANCE_CERTIFICATE"),
    document("D1998", "deed-1998.pdf", "SALE_DEED"),
    document("D2010", "deed-2010.pdf", "SALE_DEED"),
    document("D2018", "deed-2018.pdf", "SALE_DEED"),
    document("BAD", "bad.pdf", "SALE_DEED", status="classification_failed"),
]


def transaction(number, date, transferors, transferees, sources, status="corroborated"):
    return {
        "transaction_number": number,
        "transaction_type": "Sale",
        "executed_date": date,
        "registration_date": None,
        "transferors": list(transferors),
        "transferees": list(transferees),
        "summary_points": ["Sale of Sy.No.45."],
        "source_refs": [{"doc_id": doc, "filename": f"{doc}.pdf"} for doc in sources],
        "evidence_status": status,
    }


def phase_a_result():
    links = [
        ("PA-TC-0001", "1234/1998", "01-01-1998", ["Anand Rao"], ["Basavaraj"], ["EC", "D1998"]),
        ("PA-TC-0002", "555/2010", "01-01-2010", ["Basavaraj"], ["Chandrashekar"], ["EC", "D2010"]),
        ("PA-TC-0003", "777/2018", "01-01-2018", ["Chandrashekar"], ["Deepa"], ["EC", "D2018"]),
    ]
    return {
        "property_identity": {"details": []},
        "phase_a_hash": "hash-1",
        "title_chain": [
            {
                "tx_id": tx_id,
                "chain_position": position,
                "continues_previous": position > 1,
                "documented_transaction": transaction(number, date, frm, to, sources),
                "related_events": [],
            }
            for position, (tx_id, number, date, frm, to, sources) in enumerate(links, start=1)
        ],
    }


def new_case_file():
    return cf.from_phase_a("CASE1", phase_a_result(), DOCUMENTS)


def scripted_model(*steps):
    """A FunctionModel that plays ``steps`` in order, one per model request.

    Each step is a list of ``(tool_name, args)`` calls, where ``"result"`` stands
    for the agent's final-result tool, or a callable ``(messages, info) -> list``
    for steps that depend on what the model has seen.
    """
    from pydantic_ai import ModelResponse, ToolCallPart
    from pydantic_ai.models.function import FunctionModel

    pending = list(steps)

    def respond(messages, info):
        model.last_messages = list(messages)
        step = pending.pop(0)
        calls = step(messages, info) if callable(step) else step
        return ModelResponse(
            parts=[
                ToolCallPart(info.output_tools[0].name if name == "result" else name, args)
                for name, args in calls
            ]
        )

    model = FunctionModel(respond)
    model.pending = pending
    model.last_messages = []
    return model


def retry_prompts(messages):
    """The rejection messages sent back to the model during a run."""
    prompts = []
    for message in messages:
        for part in message.parts:
            retried = part.part_kind == "tool-return" and getattr(part, "outcome", None) == "retried"
            if retried or part.part_kind == "retry-prompt":
                prompts.append(str(part.content))
    return prompts
