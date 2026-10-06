# Title Chain — Interactive Graph Tree Design Plan

## 1. Concept

Replace the current single-card carousel ("Title Chain Timeline") with an **interactive graph tree**:

- Every EC transaction becomes a **node** (badge showing the transaction number + a type icon).
- **Directed edges** show how the title flows through time:
  - **FORWARD edge** (Sale, Gift, Conveyance, Sale Deed) — title moves from vendor to purchaser; edge animates forward.
  - **BACKWARD edge** (Cancellation of agreement, Reconveyance, Revocation) — title returns to the earlier owner; edge animates in reverse.
  - **Side / branch nodes** — Encumbrances (mortgage, lease, agreement) attach to the owner who was in title at that moment; divergent portions attach as side branches.
- The **Sale Deed node** is the highlighted anchor of the whole graph (glowing/pulsing).
- **Clicking a node** opens a detail panel with the full transaction info for that node.

## 2. Data → Graph derivation

Input: `TitleChainEntry[]` (flat list, already ordered by `transaction_index`).

### Primary: LLM derives the graph (logical, per case)

The graph structure must be **reasoned by the LLM per case**, not inferred by deterministic rules — EC ledgers have inconsistent party names, missing parties, GPA holders, and cancellations that a name-matching algorithm would get wrong.

We extend the **title-chain LLM pass** (it already sees the full EC ledger + SD and assigns `chain_role`) to also emit explicit graph metadata for every entry:

| New field | Meaning |
|---|---|
| `graph_from` | `transaction_index` this entry's edge starts from (the prior owner's entry); `null`/`"root"` if it connects from the original root owner |
| `graph_to` | `transaction_index` this entry's edge points to (the new owner's entry); `null`/`"current"` if the title stops here |
| `edge_type` | `"forward"` (title moves to a new owner), `"backward"` (cancellation/reconveyance — title returns to the earlier owner), `"branch"` (encumbrance / divergent portion — side node) |
| `owner_node` | a stable, normalized label identifying the owner node this entry transfers *to* (the LLM merges identical owners across entries by judgment — e.g. "Rajeshwari Potdar (or her GPA)") |

The LLM produces a genuinely **logical tree per case**: it decides which transaction is the root, which entries are the same owner continuing, where cancellations loop back, and what hangs off as encumbrances.

### Fallback: deterministic owner-state machine

Used **only** when an entry lacks LLM graph metadata (older data / model failure):

1. Walk entries in `transaction_index` order.
2. Track "current owner" (starts from earliest predecessor's vendors or a virtual root).
3. Title transfer → forward edge to purchasers; cancellation/reconveyance → backward edge to previous owner; encumbrance/divergent → dashed side node.
4. Merge nodes by **normalized** owner names.

The frontend renders whatever graph the backend returns — so even the fallback is displayed identically, just less "smart".

| Field | Use in graph |
|---|---|
| `transaction_index` | Node number + chronological order |
| `transaction_type` | Icon + forward/backward/branch classification |
| `chain_role` | Anchor (THE_SD), side vs main-line placement |
| `graph_from` / `graph_to` | Edge endpoints (LLM-provided) |
| `edge_type` | forward / backward / branch |
| `owner_node` | Node merging + detail text |
| `is_title_transfer` | Main line vs encumbrance side node |
| `parties.vendors / purchasers` | Detail panel (from/to) |
| `execution_date` | Timeline position |
| `share_fraction / portion` | Divergent branch marker |
| `explanation` | Shown in detail panel |

## 3. Graph tree design (mock)

```
                     ┌─────────────────────────────────────────────┐
                     │                                             │
                     ▼                                             │
 [ROOT OWNER]  ──► [① SALE 1998] ──► [② GIFT 2003] ──► [③ SD 2009]★  │  current owner
 (virtual)          forward           forward           forward     │
                                                                   ▼
                                                                 [⑤ SALE 2015]
                                                                  forward ▲
                                                                   │      │
                                              ┌────────────────────┘      │
                                              │                          │
                                         [④ CANCEL 2013]            [⑦ MORTGAGE 2019]
                                         (backward edge ⬅)          (encumbrance, dashed)
                                              │
                                              │
                                         [⑥ LEASE 2018]
                                         (encumbrance, dashed)
```

- Main line = chronological title flow. All main-line nodes share one horizontal lane.
- Backward edges (④ cancellation) curve back up/left with a reverse-pointing arrowhead and animate **in the reverse direction** (red/amber).
- Encumbrances (⑥ lease, ⑦ mortgage) hang **below** the owner node as dashed side nodes.
- ★ = the Sale Deed — the anchor.

## 4. Layout algorithm

Zero-dependency layered layout rendered in **inline SVG** (native, crisp, responsive):

- **X axis** = time (`execution_date`, ties broken by `transaction_index`).
- **Y axis** = owner "lanes" — each distinct owner gets a lane; node sits in its owner's lane.
- Forward edges = bezier curves from vendor node to purchaser node.
- Backward edges = bezier loop back to the previous owner (drawn above/left of the forward line so they never overlap).
- Encumbrance / divergent = small nodes stacked vertically beneath the owner node they attach to.
- Node radius fixed (≈22px), spacing auto-computed from count; canvas height grows as needed.

## 5. Animation

- **Forward edge:** "marching ants" — animated dashes moving in the forward direction (CSS `stroke-dashoffset` keyframes) + a moving arrowhead.
- **Backward edge:** same marching-dash effect but **reversed** direction, red/amber color.
- **Node entrance:** nodes pop in sequentially from the root outward (staggered), as if tracing history.
- **Sale Deed node:** slow glow pulse — the anchor.
- **Hover:** node scales up, connected edges highlight.
- **Click:** detail panel slides in.

## 6. Interaction

- Click node → **detail panel** showing (reusing the existing `ChainCard` data):
  Transaction type, Entry #, Date, Property, Registration, Share, Parties (from/to), Financials, Explanation, Role label.
- Detail panel placement options (TBD below): inline below the graph, or a right-side drawer.
- Keyboard arrow navigation between nodes (optional, low cost).
- Many-nodes safety: horizontal scroll / zoom (defer unless needed).

## 7. Implementation steps

1. **Backend (title-chain prompt + schema):** extend the LLM pass to emit `graph_from`, `graph_to`, `edge_type`, `owner_node` per entry; persist them in the saved chain. Add the deterministic fallback builder for entries missing graph metadata.
2. **`buildChainGraph(chain)`** util → `{ nodes, edges, layers }` — consumes the LLM graph fields (or fallback), computes SVG layout.
3. **`ChainGraph`** SVG component (nodes, edge paths, arrowheads) — replaces the current carousel render; keeps `ChainCard` for the detail panel.
4. Edge path + arrowhead computation.
5. Animation CSS (`stroke-dashoffset` marching ants, entrance stagger, SD pulse).
6. Detail panel + click wiring.
7. Responsive: auto-shrink + horizontal scroll; on very small screens fall back to the existing card carousel.

## 8. Decisions needed from you

1. **Node shape:** circular badges (number + icon) vs small rounded cards?
2. **Detail panel:** inline below the graph vs right-side drawer?
3. **Mobile fallback:** keep the card carousel on small screens, or always show the graph (scrollable)?
4. **Edge animation style:** marching dashes vs animated arrowheads vs both?
