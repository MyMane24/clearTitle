# LLM Prompts — Title Chain & Cross-Document Verification

Both case-level passes use one shared **system instruction**, and each sends its own **user prompt** plus an **expected output shape** to Gemini (`gemini-2.5-flash`, temperature `0.0`).

Source files:

- Shared executor / system instruction: `backend/integrations/llm/analysis_executor.py`
- Title chain prompt: `backend/services/title_chain.py`
- Verification prompt: `backend/services/verify.py`

---

## 1. Shared System Instruction (sent with every call)

Sent as `system_instruction` via the Gemini API, appended with the task-specific expected output shape:

```
You are a meticulous Karnataka property-title analyst.
Return ONLY valid JSON matching the requested output shape. Use exact enum values where specified. Do not fabricate facts.

EXPECTED OUTPUT SHAPE:
<JSON of the response schema for the current task — see below>
```

---

## 2. Title Chain Establishment

### Purpose

One Gemini call reads the Sale Deed's **property schedule** (exactly what share/portion is conveyed) and every EC ledger entry's **property description** (which share/portion each covers), classifies each matched entry's role in the **title tree**, and explains how the pieces connect. Deterministic code then merges that enrichment onto the ledger entries and sorts them chronologically to build the chain.

This matters for subdivided properties: a vendor who owned a whole plot can sell different shares/portions to different buyers on different dates (e.g. `1/2 undivided share` in 2008, balance with building in 2009). Those are **different branches** of the property tree, not contradictions — the prompt makes the LLM say so explicitly.

### Expected output shape (`MATCH_RESPONSE_SCHEMA`)

```json
{
  "sd_property": {
    "conveyed_interest": "exact share/portion the Sale Deed conveys, e.g. '1/2 undivided common share'",
    "property_identity": "Plot/CTS/Survey number + locality",
    "registration_reference": "Sale Deed registration number"
  },
  "transactions": [
    {
      "transaction_index": 25,
      "chain_role": "THE_SD | PREDECESSOR_TITLE | SUBSEQUENT_TRANSFER | DIVERGENT_BRANCH | ENCUMBRANCE | UNRELATED",
      "portion": "exact share/portion this entry covers, e.g. '1/2 undivided share', 'balance share with building'",
      "share_fraction": "1/2",
      "property_identity": "Plot/CTS/Survey + locality for this entry",
      "explanation": "plain-language explanation of this entry's role in the title story"
    }
  ],
  "title_story": "3-5 sentence plain-language summary of how title to the conveyed share was built"
}
```

### User prompt

See `MATCH_RESPONSE_SCHEMA` and the prompt in `backend/services/title_chain.py` (STEP 1 understand the SD's conveyed interest, STEP 2 read each EC entry's description, STEP 3 classify with `chain_role`, STEP 4 write the title story).

### `chain_role` semantics

- `THE_SD` — the entry is the Sale Deed's own registration.
- `PREDECESSOR_TITLE` — a title transfer on the **same portion** as the SD, before the SD.
- `SUBSEQUENT_TRANSFER` — a title transfer on the **same portion** after the SD (red flag).
- `DIVERGENT_BRANCH` — a transaction on the same property but a **different share/portion** than the SD conveys.
- `ENCUMBRANCE` — non-title document (mortgage/lease/agreement-to-sell/cancellation).
- `UNRELATED` — different survey/locality (same plot number coincidentally); excluded from the chain.

Where:

- `sd_data` = the Sale Deed's extracted `structured_json` (full extraction schema)
- `ledger` = the EC's `historical_ledger` array (full extracted ledger entries)

### Deterministic post-processing (code, not LLM)

- Only integer `transaction_index` values are kept.
- LLM `chain_role` values are validated against the allowed set; invalid/absent ones fall back to a deterministic classifier (`_fallback_role`) that detects the SD entry by registration/date, encumbrances by transaction-type keywords, and predecessor/subsequent by date relative to the SD.
- `UNRELATED` entries are dropped; if the LLM matched nothing the entire ledger is used as fallback.
- Each matched entry is enriched with `chain_role`, `is_sale_deed_entry`, `is_title_transfer`, `portion`, `share_fraction`, `property_identity`, and `explanation` (LLM values, else deterministic defaults).
- Matched entries are sorted by `execution_date` (normalized via `_parse_date`), then by `transaction_index`.
- Result is persisted to `title_chains` as status `complete`; `title_story` and `sd_property` are stored in the `source` JSON so the UI can render the title tree with a plain-language story. If no EC exists or the EC ledger has no transactions, **no title chain is built** — the chain is saved as status `no_transactions` with an empty `chain`, and the UI tells the user that no transactions exist for this property in the EC and to upload a valid EC.

---

## 3. Cross-Document Verification

### Purpose

The Sale Deed (SD) is the **source of truth** for what was conveyed; the EC ledger must be consistent with it. One LLM pass compares material fields and returns `VERIFIED / NOT_VERIFIED / N/A` items. Code validates the enums, computes the summary/verdict, persists results, and updates `cases.verification_status` / `cases.verdict`.

### Expected output shape (`VERIFY_RESPONSE_SCHEMA`)

```json
{
  "items": [
    {
      "field": "Property survey/CTS number",
      "sd_value": "value from Sale Deed",
      "ec_value": "value from EC ledger",
      "status": "VERIFIED | NOT_VERIFIED | N/A",
      "notes": "explanation"
    }
  ],
  "overall_comment": "free text summary of title exposure"
}
```

### User prompt

```
Verify the Karnataka Sale Deed (SD) against the Encumbrance Certificate
(EC) historical ledger for the same property. The SD is the source of
truth for what was conveyed; the EC ledger must be consistent with it.

Compare each material field listed below. For each, produce one item:
- status VERIFIED: SD value and EC value agree (or EC confirms the SD transaction)
- status NOT_VERIFIED: they conflict, or the SD claims an encumbrance-free title
but the EC shows a conflicting transaction
- status N/A: the field is absent/blank in one or both documents

--- SALE DEED ---
<json.dumps(sd_data)>

--- EC HISTORICAL LEDGER ---
<json.dumps(ledger)>

Fields to compare: property identifiers (CTS/survey/plot numbers, locality),
execution/registration date, parties (vendors/purchasers), consideration amount.
Pay special attention to whether the EC shows any later encumbrance (mortgage,
sale, agreement) on the property AFTER the SD date.
```

### Deterministic post-processing (code, not LLM)

- Status is uppercased; anything outside `{VERIFIED, NOT_VERIFIED, N/A}` is forced to `N/A`.
- Summary counts per status and computes the verdict:

  | Condition | Verdict |
  |---|---|
  | `NOT_VERIFIED == 0` and `VERIFIED > 0` | `VERIFIED` |
  | `VERIFIED == 0` and `NOT_VERIFIED > 0` | `NOT_VERIFIED` |
  | `VERIFIED == 0` and `NOT_VERIFIED == 0` | `N/A` |
  | otherwise (both present) | `NOT_VERIFIED` |

- Results persist to `verification_results`; the case row gets `verification_status=complete` and the computed `verdict`.
