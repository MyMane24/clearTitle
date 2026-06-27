"""
Statute-grounded RAG layer for verification.
Chunks the Karnataka property due-diligence reference guide by section,
embeds into a Qdrant collection, and retrieves top-k relevant statute chunks
for grounding verification_notes and cross-doc findings.
"""

from __future__ import annotations

import hashlib
import json
import os
import re

from dotenv import load_dotenv
from google import genai

from backend.logger import get_logger

load_dotenv()

logger = get_logger(__name__)

EMBEDDING_MODEL = "gemini-embedding-001"
COLLECTION_NAME = "karnataka_statutes"
DEFAULT_TOP_K = 3

_client = None
_qdrant_client = None


def _get_genai_client():
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        raise ValueError("GEMINI_API_KEY not set in .env")
    return genai.Client(api_key=api_key)


def _ensure_qdrant():
    global _qdrant_client
    if _qdrant_client is not None:
        return _qdrant_client
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import VectorParams, Distance
    except ImportError:
        raise RuntimeError("qdrant-client not installed")

    _qdrant_client = QdrantClient(path="./data/qdrant_db")
    if not _qdrant_client.collection_exists(collection_name=COLLECTION_NAME):
        _qdrant_client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=768, distance=Distance.COSINE),
        )
    return _qdrant_client


def _embed(text: str) -> list[float]:
    client = _get_genai_client()
    result = client.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=text,
        config={"output_dimensionality": 768},
    )
    return result.embeddings[0].values


# ── Reference statute chunks ──────────────────────────────────────────────

STATUTE_CHUNKS = [
    {
        "section": "KLR Act, 1964 — Section 4 (Definitions)",
        "text": "Section 4 of the Karnataka Land Revenue Act, 1964, defines key terms including 'survey number', 'tenure', 'occupant', 'holder', and 'mutation'. "
                "Holder means a person in lawful possession of land. Mutation refers to the recording of a change in title or possession in revenue records. "
                "Survey numbers are unique identifiers assigned to parcels of land. CTS (City Survey) numbers are the urban equivalent used in municipal areas.",
        "doc_types": ["SALE_DEED", "PROPERTY_REGISTER_CARD", "MUTATION", "ENCUMBRANCE_CERTIFICATE"],
        "keywords": ["survey number", "CTS", "mutation", "holder", "tenure", "KLR Act"]
    },
    {
        "section": "Registration Act, 1908 — Section 17 (Documents requiring registration)",
        "text": "Section 17 of the Registration Act, 1908, mandates compulsory registration for documents that create, declare, assign, limit or extinguish any right, title or interest in immovable property valued at Rs. 100 or more. "
                "This includes Sale Deeds, Gift Deeds, Partition Deeds, and mortgages. Without registration, such documents do not confer title and are inadmissible as evidence of the transaction under Section 49.",
        "doc_types": ["SALE_DEED", "GIFT_DEED", "PARTITION_DEED"],
        "keywords": ["registration", "Section 17", "compulsory registration", "admissible"]
    },
    {
        "section": "Registration Act, 1908 — Section 32 (Time of presentation)",
        "text": "Section 32 read with Section 23 of the Registration Act requires that a document be presented for registration within four months of its execution date. "
                "The execution date must therefore ALWAYS precede the registration date. If execution_date is after registration_date, it indicates either data entry error or a potentially fraudulent document.",
        "doc_types": ["SALE_DEED", "GIFT_DEED", "PARTITION_DEED"],
        "keywords": ["execution date", "registration date", "Section 32", "four months"]
    },
    {
        "section": "Karnataka Stamp Act, 1957 — Section 3 (Stamp duty chargeable)",
        "text": "Section 3 of the Karnataka Stamp Act, 1957, read with the Schedule, prescribes stamp duty on instruments. For Sale Deeds, stamp duty is payable at rates specified in Article 20 of the Schedule. "
                "The current rate is approximately 5-8% of the declared consideration or guidance value, whichever is higher. "
                "Deficiency in stamp duty renders the document impounded by the registering authority under Section 33.",
        "doc_types": ["SALE_DEED", "GIFT_DEED"],
        "keywords": ["stamp duty", "consideration", "Section 3", "Karnataka Stamp Act"]
    },
    {
        "section": "Karnataka Stamp Act, 1957 — Section 47A (Undervaluation of instruments)",
        "text": "Section 47A of the Karnataka Stamp Act, 1957, empowers the Deputy Commissioner to take action where the market value of property is understated in an instrument. "
                "If the registering officer has reason to believe the market value is understated, they refer the matter to the Deputy Commissioner for determination of proper stamp duty. "
                "The form 1-A communication is issued to the parties. A deed with prevention_of_undervaluation_referred=True is a significant risk flag indicating potential tax evasion or Benami transaction indicators.",
        "doc_types": ["SALE_DEED"],
        "keywords": ["undervaluation", "Section 47A", "Benami", "market value", "form 1-A", "prevention of undervaluation"]
    },
    {
        "section": "Transfer of Property Act, 1882 — Section 3 (Attestation)",
        "text": "Section 3 of the Transfer of Property Act, 1882, defines 'attested' and requires that a deed be attested by at least two witnesses. "
                "A witness must have seen the executant sign the instrument or received a personal acknowledgment of the signature. "
                "A deed lacking two attesting witnesses is defective and may not be admitted in evidence. "
                "For mortgages by deposit of title deeds, the requirement of attestation has been subject to judicial interpretation.",
        "doc_types": ["SALE_DEED", "GIFT_DEED", "PARTITION_DEED", "MORTGAGE_DEED"],
        "keywords": ["witness", "attestation", "Section 3", "Transfer of Property Act"]
    },
    {
        "section": "Indian Evidence Act, 1872 — Section 90 (Presumption as to documents 30 years old)",
        "text": "Section 90 of the Indian Evidence Act, 1872, provides that a document purporting to be 30 years old or more, produced from proper custody, may be presumed to have been duly executed and attested. "
                "For title due diligence, a 30-year chain of title is the gold standard under this provision. An EC search period of 13-30 years is considered adequate for marketable title. "
                "If the total document coverage is less than 13 years, it is insufficient for confident title certification.",
        "doc_types": ["ENCUMBRANCE_CERTIFICATE", "SALE_DEED"],
        "keywords": ["30 years", "Evidence Act", "Section 90", "chain of title", "search period"]
    },
    {
        "section": "RERA Act, 2016 — Section 3 (Registration of projects)",
        "text": "Section 3 of the Real Estate (Regulation and Development) Act, 2016 (RERA), mandates that any real estate project with land area exceeding 500 sqm or eight units must be registered with the state RERA authority. "
                "Promoters cannot advertise, book, sell or offer for sale without registration. In Karnataka, RERA registration number format is 'PRM/KA/...'. "
                "The absence of RERA registration for an apartment or plotted development project is a significant legal risk and should be flagged for external verification since the registration status cannot be confirmed from documents alone.",
        "doc_types": ["SALE_DEED", "BUILDER_BUYER_AGREEMENT"],
        "keywords": ["RERA", "apartment", "project", "registration", "promoter", "builder-buyer"]
    },
    {
        "section": "Benami Transactions (Prohibition) Act, 1988 — Section 2 (Definitions)",
        "text": "The Benami Transactions (Prohibition) Act, 1988, prohibits transactions where property is held by one person but consideration is paid by another, with no beneficial interest in the ostensible owner. "
                "Indicators of benami transactions include: consideration paid in cash far below market value, purchase in the name of a person of limited means, "
                "undervaluation of stamp duty triggering Section 47A, and name variations between different documents for the same property. "
                "These should be flagged with heightened severity when multiple indicators are present.",
        "doc_types": ["SALE_DEED", "ENCUMBRANCE_CERTIFICATE"],
        "keywords": ["benami", "undervaluation", "cash payment", "Benami Act"]
    },
    {
        "section": "Karnataka Land Revenue Act, 1964 — Sections 127-130 (Mutation procedure)",
        "text": "Sections 127 to 130 of the Karnataka Land Revenue Act, 1964, govern mutation of entries in revenue records. "
                "Upon transfer of land, the transferee must apply for mutation within three months. The Tahsildar conducts an inquiry and passes orders. "
                "Mutation does NOT confer title but merely records the fact of possession/transfer in revenue records. "
                "A mutation entry without a corresponding registered deed is insufficient to prove ownership but the absence of mutation after a registered sale is suspicious.",
        "doc_types": ["MUTATION", "SALE_DEED", "RTC_PAHANI"],
        "keywords": ["mutation", "revenue records", "title", "Tahsildar", "Section 127"]
    },
    {
        "section": "Indian Succession Act, 1925 — Sections 370-374 (Succession Certificate)",
        "text": "Under the Indian Succession Act, 1925, a Succession Certificate is required to establish the right of legal heirs to assets of a deceased person. "
                "For property inheritance, a Legal Heir Certificate (from the Tahsildar), Succession Certificate (from the Civil Court), or a registered Will probated by a Court is necessary. "
                "If an EC transaction shows 'by inheritance' or 'by death' as the transfer mode but no succession document is present in the bundle, this is a legal gap that must be flagged.",
        "doc_types": ["LEGAL_HEIR_CERTIFICATE", "ENCUMBRANCE_CERTIFICATE", "SALE_DEED"],
        "keywords": ["succession", "inheritance", "legal heir", "death", "Succession Certificate", "Will"]
    },
    {
        "section": "Registration Act, 1908 — Section 49 (Effect of non-registration)",
        "text": "Section 49 of the Registration Act, 1908, provides that an unregistered document affecting immovable property is not admissible as evidence of the transaction. "
                "An unregistered Sale Deed, Gift Deed, or mortgage cannot be used to prove title. "
                "However, an unregistered document may still be admissible as evidence of collateral facts (e.g., possession). "
                "All Sale Deeds, Gift Deeds, and Partition Deeds in the bundle must have registration details populated. Absence of registration_number is a critical defect.",
        "doc_types": ["SALE_DEED", "GIFT_DEED", "PARTITION_DEED"],
        "keywords": ["unregistered", "Section 49", "admissible", "registration number", "collateral"]
    },
    {
        "section": "Power of Attorney Act, 1882 — Section 4 (Deposit of original)",
        "text": "Under the Power of Attorney Act, 1882, a Power of Attorney (POA) must be duly stamped and registered if it confers authority to sell or transfer immovable property. "
                "An unregistered POA for sale of immovable property is invalid. "
                "POAs require notarization and, where the agent is authorized to sell property, registration. "
                "An undated POA is defective. When a corporate entity, HUF, or trust is the seller, the authority document (Board Resolution, POA, Trust Deed) must be examined.",
        "doc_types": ["SALE_DEED"],
        "keywords": ["power of attorney", "POA", "Board Resolution", "authority", "HUF", "trust"]
    },
    {
        "section": "Contract Act, 1872 — Section 62 (Effect of novation)",
        "text": "Section 62 of the Indian Contract Act, 1872, deals with novation — the substitution of a new contract for an existing one. "
                "In property transactions, novation is relevant when party names or property descriptions differ between the agreement and the deed. "
                "If agreement parties and deed parties differ materially without explanation, the enforceability of the transaction may be affected.",
        "doc_types": ["SALE_DEED", "PARTITION_DEED"],
        "keywords": ["novation", "party mismatch", "Contract Act"]
    },
    {
        "section": "Income Tax Act, 1961 — Section 269SS/269ST (Cash transaction limits)",
        "text": "Sections 269SS and 269ST of the Income Tax Act, 1961, prohibit taking or accepting loans/deposits or receiving any sum of Rs. 2 lakh or more in cash. "
                "Real estate transactions exceeding Rs. 2 lakh must be by account payee cheque/draft or electronic transfer. "
                "A declared_consideration_amount in cash exceeding this limit is a red flag for Benami, money laundering, or stamp duty evasion. "
                "It should be flagged with high severity.",
        "doc_types": ["SALE_DEED"],
        "keywords": ["cash", "Income Tax Act", "Section 269ST", "cheque", "banking"]
    },
    {
        "section": "Karnataka Municipal Corporations Act, 1976 — Property Tax",
        "text": "Property tax is levied by municipal corporations (BBMP, etc.) under the Karnataka Municipal Corporations Act, 1976. "
                "The Property ID (PID) is a unique identifier assigned to each property. Tax arrears create a charge on the property. "
                "A property tax receipt showing 'Arrears' or 'Due' status indicates the property has unpaid taxes, which a purchaser would inherit under Section 100 of the Transfer of Property Act, 1882. "
                "Current year tax receipts should be verified in any due diligence.",
        "doc_types": ["PROPERTY_TAX_ASSESSMENT", "E_PAYMENT_RECEIPT", "TAX_RECEIPT"],
        "keywords": ["property tax", "PID", "arrears", "BBMP", "municipal"]
    },
]

DOC_TYPE_STATUTE_MAP: dict[str, list[str]] = {}
for chunk in STATUTE_CHUNKS:
    for dt in chunk["doc_types"]:
        DOC_TYPE_STATUTE_MAP.setdefault(dt, []).append(chunk["section"])


def initialize_statute_store():
    """Embed and index all statute chunks into Qdrant if not already present."""
    qclient = _ensure_qdrant()
    from qdrant_client.models import PointStruct

    existing = qclient.count(collection_name=COLLECTION_NAME).count
    if existing > 0:
        logger.info("Statute store already has %d chunks", existing)
        return

    points = []
    for i, chunk in enumerate(STATUTE_CHUNKS):
        text = f"[{chunk['section']}] {chunk['text']}"
        embedding = _embed(text)
        point_id = abs(hash(chunk["section"])) % (10 ** 12)
        points.append(PointStruct(
            id=point_id,
            vector=embedding,
            payload={
                "section": chunk["section"],
                "text": chunk["text"],
                "keywords": chunk["keywords"],
                "doc_types": chunk["doc_types"],
                "chunk_index": i,
            },
        ))
    qclient.upsert(collection_name=COLLECTION_NAME, points=points)
    logger.info("Indexed %d statute chunks into Qdrant", len(points))


def retrieve_statute_context(doc_type: str, query: str | None = None, top_k: int = DEFAULT_TOP_K) -> list[dict]:
    """
    Retrieve top-k relevant statute chunks for the given doc_type and optional query.
    """
    qclient = _ensure_qdrant()
    try:
        qclient.count(collection_name=COLLECTION_NAME)
    except Exception:
        initialize_statute_store()

    # Build a query string combining doc_type + any specific issue query
    search_query = f"{doc_type} property document verification due diligence"
    if query:
        search_query = f"{query} {doc_type}"

    embedding = _embed(search_query)
    results = qclient.search(
        collection_name=COLLECTION_NAME,
        query_vector=embedding,
        limit=top_k,
    )

    # Filter by doc_type relevance if enough results
    contexts = []
    for r in results:
        payload = r.payload
        payload["relevance_score"] = round(r.score, 3)
        contexts.append(payload)

    # Sort so best-scored appears first
    contexts.sort(key=lambda x: x["relevance_score"], reverse=True)
    return contexts


def format_statute_context(contexts: list[dict]) -> str:
    """Format retrieved statute chunks into a prompt-ready context block."""
    if not contexts:
        return ""
    lines = ["## RELEVANT STATUTE REFERENCES (Ground your legal citations here)"]
    for i, ctx in enumerate(contexts, 1):
        lines.append(f"\n### Reference {i}: {ctx['section']} (relevance: {ctx['relevance_score']})")
        lines.append(ctx["text"])
    return "\n".join(lines)


def verify_citation(contexts: list[dict], legal_detail: str) -> dict:
    """
    Lightweight check: if legal_detail cites a section number that doesn't
    appear in the retrieved context, flag the finding as low confidence.
    Returns {"confidence_downgrade": float, "reason": str}
    """
    section_pattern = r'(?:Section|Sec\.?|S\.?)\s*(\d+[A-Z]?(?:A|B|C)?)'
    cited_sections = re.findall(section_pattern, legal_detail, re.IGNORECASE)
    if not cited_sections:
        return {"confidence_downgrade": 0, "reason": ""}

    context_text = " ".join(c["text"] + " " + c["section"] for c in contexts)
    uncited = [s for s in cited_sections if s not in context_text]

    if uncited:
        return {
            "confidence_downgrade": 0.3,
            "reason": f"Cited section(s) {', '.join(uncited)} not found in retrieved statute context. Finding flagged for human review.",
        }
    return {"confidence_downgrade": 0, "reason": ""}
