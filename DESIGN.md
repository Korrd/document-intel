# Pixels to Action — Designing a Multi-Agent Visual Intelligence System

**Workshop #CodeMeet Barcelona, 15-10 · Accenture & Codemotion**

**Group:** `__`
**Members:** `__________`, `__________`, `__________`, `__________`

> `Document / Image → Understanding → Reasoning → Answer / Action`

This is a design deliverable. No implementation — the goal is to state the decisions we took, the alternatives we rejected, and why. A presentation deck of the same content is in [`deck.html`](./deck.html).

---

## 1. How we interpreted the challenge, and the scope we defined

### The real problem

The information is already in the documents. It just isn't *reachable* — because the documents arrive as pixels, and because they are not homogeneous.

The naive reading of the brief is "do OCR, then put a chatbot on top." We rejected that framing, because of what the users actually ask (below): only one of the five question types is satisfied by a text transcript. The other four require layout understanding, cross-document structure, or inference. So we treated this as a **perception + retrieval + grounded reasoning** problem, not a text-extraction problem.

### Users and actors

| Actor | What they need | Pain today |
|---|---|---|
| Ops / back-office analyst | Find a specific value inside a file, fast | Opens the PDF and reads it by hand |
| Legal & compliance reviewer | Locate clauses, obligations, deviations from standard | No search across scans; full manual review |
| Risk / credit officer | Consistency across several documents in one file | Cross-checking is manual and inconsistently done |
| Downstream systems | Structured fields, not prose | Re-keyed by hand, or not captured at all |
| **Model risk / audit (second line)** | Reconstruct how an answer was produced | Nothing to inspect |

That last actor is the one most easily forgotten, and it is the one that constrains the architecture the most: in a regulated institution, an answer without a reconstructable provenance chain is not usable, no matter how accurate it is.

### Query taxonomy — the thing that drove the design

1. **Lookup** — "What is the IBAN on this contract?" → one value, one place.
2. **Aggregate** — "Total charges across these 12 statements." → requires structure across documents.
3. **Compare** — "Does the deed match the loan application?" → requires two documents, aligned.
4. **Infer** — "Is there an early-repayment penalty?" → requires interpretation, may be implicit.
5. **Act** — "Flag this file for manual review." → requires tools and a permission model.

Design consequence: a single RAG-over-OCR-text path handles (1) and partially (4), and fails (2), (3) and (5). That is why the system is multi-agent with a planner and multiple retrieval paths rather than one pipeline.

### Document characteristics that condition the design

- Multiple documents concatenated in a single scanned PDF → we must split before anything else.
- Tables, including merged cells and multi-page tables → layout matters, text order does not survive flattening.
- Stamps, signatures, handwritten annotations, strike-throughs → semantically meaningful, invisible to OCR.
- Variable scan quality, skew, rotation → quality must be measured, not assumed.
- Numeric and identifier fields (amounts, IBAN, NIF, dates) → single-character errors are both silent and expensive.

### Constraints

- Regulated financial sector: PII, EU data residency, retention limits, no client data into model training.
- Auditability is a hard requirement, not a feature.
- **Asymmetric error cost**: a confidently wrong number is far more damaging than an abstention. This single asymmetry is the backbone of every trust decision below.
- Volume is daily and batchy, not streaming.

### Scope — v1

**In:** scanned PDF and image input · ES/EN · two document families · field extraction with validation · grounded Q&A with citations · abstention · EU AI Act pre/post-flight gate · evidence-viewer UI · read-only answers.

**Bronze accepts more than images.** The layer is defined by heterogeneous intake — scans, photographs, spreadsheets, native PDFs — and normalizing all of it into one Silver representation. The MVP implements the image path first because it is the hard one and the one the brief is about; spreadsheets and native-text PDFs are a declared Bronze slot for phase 2, not an afterthought.

**Out, deliberately:** free-form handwriting · real-time latency · write-back to core banking · model fine-tuning · autonomous execution · multi-tenant isolation · knowledge-graph reasoning.

### Assumptions

- The corpus is known in advance, so we can pre-process rather than work on demand.
- Scans are predominantly machine-printed at ~200–300 dpi.
- A human review queue already exists that we can escalate into.
- We can call a hosted frontier vision-language model from inside the compliance perimeter.

---

## 2. Capabilities we consider key

Six capabilities. We were explicit about which ones need generative AI — three of the six do not.

| | Capability | What it does | Implementation |
|---|---|---|---|
| **C1** | Ingest & normalize | Hash + dedupe, split multi-doc PDFs, deskew, fix orientation, score quality, render page images | **Deterministic** + classical CV |
| **C2** | Perceive the page | Layout-aware reading: text, reading order, tables, key-value regions, stamps, signatures — all with bounding boxes | **VLM**, OCR as cross-check |
| **C3** | Classify & route | Document type + language → selects extraction schema and validation rules | **Rules first**, small classifier |
| **C4** | Extract to schema | Per-type JSON schema with per-field confidence and per-field provenance | **Generative**, constrained output |
| **C5** | Reason & answer | Plan the question, retrieve, re-read pixels when needed, synthesize with citations, or abstain | **Agentic** |
| **C6** | Act & escalate | Propose a next step, open a review task, emit structured output downstream | Whitelisted, logged tools |
| **C7** | Govern | Refuse prohibited inferences, classify high-risk use, enforce the autonomy ceiling, disclose, record | **Deterministic**, on the request path |

C7 is a capability rather than a policy document on purpose. Compliance that lives in a wiki is advisory; compliance that lives in the request path can refuse. It is also deliberately rule-based: a gate must be inspectable, replayable and stable across releases, and a model that occasionally refuses differently is worse than no gate at all.

### What can be extracted directly vs. what requires reasoning

- **Directly:** printed key-value fields, table cells, dates, amounts, identifiers, signature/stamp presence.
- **Requires reasoning:** clause interpretation, implicit conditions, reconciling contradictions between documents, anything phrased as "is there…" or "does X match Y".

We route these differently on purpose: the direct cases go through the cheap structured path, the reasoning cases through the expensive agentic path. Treating them identically would mean paying frontier-model cost for a field lookup, and under-serving the hard questions.

### Where agents add value, and where they don't

Agents earn their complexity where the **number of steps is not known in advance** — planning which evidence a question needs, deciding whether to re-read a page at higher resolution, judging whether a draft answer is grounded. For a fixed pipeline (ingest → read → classify → extract → validate) an agent adds latency, cost and nondeterminism for nothing. So: **ingestion is a pipeline, querying is agentic.**

### What we would deliberately *not* solve with generative AI

Deduplication; page splitting; deskew and orientation; blank-page detection; barcode/MRZ reading; checksum and format validation (IBAN, NIF, dates, amounts); totals reconciliation; confidence thresholding; routing and escalation rules; access control; all arithmetic.

**Rule we hold ourselves to: if a rule can do it, a model must not.** Rules are cheaper, unit-testable, and cannot hallucinate.

### Autonomy

Autonomy is a dial, not a property of the system. Each level is earned with measured evidence from the level below.

| Level | System does | Example | Who decides |
|---|---|---|---|
| **L0** | Answers with evidence | "The IBAN is ES91… — page 3, highlighted" | Nobody. Read-only. **This is our MVP.** |
| **L1** | Extracts & structures | Populates 14 fields of a loan record | Auto-accept above confidence τ, else human |
| **L2** | Proposes an action | "Mismatch found → suggest flag for review" | Human clicks once, fully logged |
| **L3** | Executes reversible work | Opens the review ticket, routes the file | System acts, human notified, undo available |
| **L4** | Executes irreversible work | Approves, pays, signs, writes to core banking | **Never. Out of scope by design.** |

---

## 3. Conceptual architecture and end-to-end flow

Two planes. **Ingestion runs once per document; the query plane runs many times per document.** Separating them is the central structural decision.

### The ingestion plane is a medallion

We describe the ingestion layers as **Bronze → Silver → Gold**, because the shape is already familiar to anyone who has built a data platform and because it names the one thing that matters here: what is preserved at each layer.

| Layer | Holds | Why it exists |
|---|---|---|
| **Bronze** | The page images, immutable, with sha256, dimensions and a scan-quality score | The pixels. Never discarded, never overwritten, always available to be read again |
| **Silver** | Normalized **Markdown** in reading order, plus blocks and tables, **each carrying a bounding box** | One canonical representation regardless of whether the source was a scan, a photo or a spreadsheet |
| **Gold** | Validated schema fields with confidence, provenance and validator verdicts; the retrieval index | The queryable, aggregable surface — and the only layer a query touches directly |

Markdown is the canonical Silver artifact: a single text representation that every downstream component agrees on. The critical detail, and the thing that distinguishes this from a conventional document pipeline, is that **Silver carries coordinates**. A Markdown-only Silver layer severs the link back to Bronze, and once that link is gone no amount of downstream cleverness recovers it — citation, visual verification and the pixel re-read all become impossible.

### Ingestion plane — batch

```
          ┌─────────────┐    ┌──────────────┐    ┌────────────┐    ┌───────────────┐    ┌─────────────┐
 doc ───▶ │   Intake    │──▶ │ Vision agent │──▶ │ Classifier │──▶ │ Extractor     │──▶ │ Validators  │
          │ hash/dedupe │    │ layout, read │    │ type +     │    │ agent         │    │ IBAN, dates │
          │ split       │    │ order, tables│    │ language   │    │ schema JSON + │    │ totals,     │
          │ deskew      │    │ bboxes       │    │ → schema   │    │ confidence +  │    │ cross-field │
          │ quality     │    │              │    │            │    │ provenance    │    │             │
          └─────────────┘    └──────────────┘    └────────────┘    └───────────────┘    └──────┬──────┘
                                                                                              │
     ┌──────────────────┬────────────────────────┬──────────────────────┬────────────────────┘
     ▼                  ▼                        ▼                      ▼
┌──────────┐  ┌───────────────────┐  ┌──────────────────────┐  ┌──────────────┐
│ BRONZE   │  │ SILVER            │  │ GOLD                 │  │ GOLD         │
│ Page     │  │ Document record   │  │ Hybrid index         │  │ Field store  │
│ images   │  │ markdown, tables, │  │ BM25 + embeddings    │  │ SQL — exact, │
│ (object  │  │ fields, bboxes,   │  │ + metadata filters   │  │ cheap,       │
│  store)  │  │ confidences       │  │                      │  │ aggregable   │
└──────────┘  └───────────────────┘  └──────────────────────┘  └──────────────┘
   the pixels are       coordinates survive
   never discarded      normalization
```

The artifact produced is a **Document Intelligence Record**: normalized text in reading order, tables as structured JSON, extracted fields with confidence, and a bounding box for every block and every field — plus a pointer to the page images.

**Why pre-process rather than work purely on demand?** Aggregation queries across documents are impossible without a pre-built structured store; p95 latency on a per-question VLM pass over a whole file is unacceptable; perception cost is paid once instead of per question; and a stable stored artifact is what makes the system auditable. The trade-off we accept: a schema change means a re-ingest, and a freshly uploaded document needs a cold on-demand path. We keep that on-demand path as a fallback, not as the default.

### Query plane — on demand

```
  question ──▶ ┌──────────────────┐
               │ EU AI Act gate   │  deterministic. Art. 5 prohibited-inference refusal,
               │   (pre-flight)   │  Annex III high-risk classification, Art. 14 autonomy
               └──────┬───────────┘  ceiling. Runs before any model, so a refusal costs nothing
                      ▼
               ┌──────────────┐
               │ Orchestrator │  classifies intent (lookup / aggregate / compare / infer / act)
               │   (planner)  │  and complexity, plans the route, decides when it has enough
               └──────┬───────┘
                      │ selects among tools
      ┌───────────────┼──────────────────┬─────────────────────┐
      ▼               ▼                  ▼                     ▼
┌───────────┐  ┌──────────────┐  ┌────────────────┐  ┌───────────────┐
│ SQL field │  │ Hybrid       │  │ Pixel re-read  │  │ Compute tool  │
│ lookup    │  │ retrieval    │  │ crop the page  │  │ all arithmetic│
│ exact,    │  │ + rerank,    │  │ and look again │  │ — never the   │
│ aggregate │  │ ACL-filtered │  │ (stronger VLM) │  │ LLM           │
└─────┬─────┘  └──────┬───────┘  └───────┬────────┘  └──────┬────────┘
      └───────────────┴──────────────────┴──────────────────┘
                      ▼
            ┌──────────────────┐     ┌──────────────┐     ┌──────────────────┐
            │ Synthesizer      │────▶│ Verifier     │────▶│ EU AI Act gate   │──▶ answer
            │ answer + per-    │     │ claim-level  │     │  (post-flight)   │    + citations
            │ claim citations  │     │ grounding    │     │ disclosure, data │    or ABSTAIN
            └──────────────────┘     └──────────────┘     │ minimisation,    │    → human queue
                                                          │ oversight check  │
                                                          └──────────────────┘
```

The post-flight gate is not a disclaimer generator. Art. 14 human oversight is only meaningful if there is something for a human to check, so an answer whose claims carry no citable region is **blocked there** rather than released with a warning.

### Component responsibilities

| Component | Responsibility | Explicitly not responsible for |
|---|---|---|
| Orchestrator | Intent classification, tool selection, stopping condition | Reading documents itself |
| Vision agent | Pixels → structured page representation with boxes | Business semantics |
| Extractor agent | Page representation → schema-valid JSON + provenance | Deciding whether values are plausible |
| Validators | Deterministic correctness of formats and totals | Semantic correctness |
| Retrieval | Returning candidate evidence, ACL-filtered | Judging sufficiency |
| Pixel re-read | Answering "what does this exact region actually say?" | Full-document reasoning |
| Synthesizer | A grounded answer with per-claim citations | Deciding whether to ship it |
| Verifier | Claim-vs-evidence gate; abstain or pass | Fixing the answer |

Communication is a **deterministic orchestrator calling typed tools**, not free-form agent-to-agent chat: it is traceable, testable, cheaper, and it cannot loop unboundedly. Agents do not talk to each other; they return structured results to the orchestrator.

### The one idea worth remembering: we never throw away the pixels

Most document pipelines flatten a page into text and then reason over a lossy transcript. Every downstream error inherits that loss and nothing can recover it — a merged table cell becomes a wrong number silently, a strike-through vanishes, "which column was this under?" becomes unanswerable, and re-asking harder does not help because the evidence is gone.

Instead: every extracted value keeps its page and bounding box. Low-confidence or hard questions trigger a **crop and re-read of that exact region** with a stronger model. The user is shown the highlighted crop rather than a claim about it. Resolution becomes a cost dial — a cheap pass over everything, an expensive pass only where it matters.

This is what makes the system *visual* intelligence rather than OCR with a chatbot stapled on.

### Where deterministic software ends and AI begins

**Deterministic:** orchestration, routing, retries, idempotency; retrieval and filtering; access control — applied *before* retrieval, never as a post-filter; all arithmetic and date math; format and checksum validation; confidence thresholding and escalation; audit logging.

**Model-driven:** reading an unfamiliar layout; mapping messy page content onto a clean schema; interpreting a clause or inferring from context; planning which tool a question needs; judging whether a drafted answer is grounded.

### Human intervention points

1. Field confidence below threshold at ingest → review queue.
2. Validator failure (checksum, totals don't reconcile) → review queue.
3. Verifier abstention at query time → human answers, with the crop pre-highlighted.
4. Any L2+ action → human confirms before execution.
5. Sampled QA on high-confidence output, to detect the errors nothing flagged.

In every case the human receives the specific crop, not the whole file. That is the difference between a review queue that gets worked and one that gets ignored.

---

## 4. Main risks, controls and evaluation mechanisms

### Evidence-first: the hard gate

Every claim carries document + page + bounding box. A verifier agent checks each claim against its cited span. **No citation → the answer does not ship.** Abstention is a success state, not a failure.

### Metrics

- **Groundedness / faithfulness** and citation accuracy — the primary release gate.
- **Correct-abstention rate** on deliberately unanswerable questions.
- Field-level precision, recall and exact match; table structure similarity (TEDS).
- End-to-end task success as judged by ops.
- p95 latency; cost per document and per query.

We gate on groundedness and abstention *before* raw accuracy, because of the error-cost asymmetry: a system that is 90% accurate and honest about the other 10% is usable; one that is 95% accurate and silent about the rest is not.

### Evaluation data

A golden dataset of ~300 real documents across the two families: field-level ground truth labelled by ops, OCR ground truth on a sample, and ~150 Q&A pairs of which **20% are deliberately unanswerable** (to measure abstention) and 20% adversarial near-misses (similar-looking values, stale versions, values present in a different document). Replayed nightly as a canary; a regression blocks release.

### Detecting degradation

Confidence-distribution and abstention-rate shift; per-document OCR quality trend; LLM-judge sampling on live traffic plus user thumbs-down; alerting when document layouts not seen in training/eval start appearing in the mix.

### When the system isn't sure — the fallback ladder

1. Low confidence → re-read the relevant crop with a stronger model.
2. Still low → answer partially and state explicitly what is missing.
3. Still low → **abstain** and open a review task with the crop pre-highlighted.

### Failure modes and controls

| Failure mode | Why it is dangerous here | Control |
|---|---|---|
| **Invented figures** | A plausible wrong amount enters a credit decision | Citation gate, verifier, arithmetic outside the model, abstention |
| **Digit-level OCR error** | 8→3 in an IBAN or an amount passes every text-level check | Checksum validation, totals reconciliation, dual-pass on numerics, pixel re-read |
| **Prompt injection inside a document** | A scanned page containing "ignore your instructions" is attacker-controlled input | Document content is treated as **data, never instruction**; strict role separation; agents hold no destructive tools; no outbound network tools in the query plane |
| **PII leakage / wrong-eyes access** | Regulated data, real customers | Redaction at ingest of PII not needed downstream; ACL filters applied pre-retrieval; EU residency; no client data into training; retention limits |
| **Silent degradation** | A new scanner or layout quietly drops accuracy | Nightly canary replay, drift alerts, layout-novelty detection |
| **Over-trust by users** | Confident prose stops being checked | Evidence shown by default, confidence surfaced, abstentions made visible rather than hidden |
| **Cost blow-up** | Frontier VLM on every page of every query | Pre-processing; complexity-tiered models so cheap questions get a cheap model; escalation only when confidence is actually low |
| **Role and entitlement drift** | In a bank, *who may see which document* changes constantly, and a stale entitlement is a data breach with an audit trail | Entitlements resolved at query time from the identity provider, never cached in the index; ACL filters applied **pre-retrieval**; every access written to the trace |
| **Scalability and resilience** | Ingestion is batchy and bursty, and the model gateway is a third-party dependency that will have bad days | Ingestion is an idempotent queue keyed on sha256, so a failed batch is replayed rather than reconciled; per-stage retries with backoff; the query plane degrades to the structured path when the gateway is unavailable, answering lookups and abstaining on reasoning rather than failing closed entirely |

### Observability

One trace per question: the plan, documents retrieved, crops re-read, prompts, model versions, confidences, token cost. Fully replayable, so we can always reconstruct **why** the system produced a given answer. That trace *is* the compliance artifact — it is not logging added afterwards, it is part of the deliverable.

---

## 5. What we would build as the MVP, and what we would leave for later

### MVP — the thin slice

- Two document families, ~500 real documents.
- Ingestion → VLM read → 10–14 field schema → deterministic validators.
- Hybrid retrieval plus grounded Q&A with citations and abstention.
- Evidence viewer: the answer side by side with the highlighted crop.
- Eval harness with 150 golden Q&A pairs wired into CI.
- **Three agents only:** orchestrator, extractor, verifier. Not a swarm.

Priority use case: **lookup and extraction on a single document**, because it is the highest-volume real question and the cheapest path to a trustworthy demo. Aggregation across documents comes second.

### Deliberately simplified

Read-only (L0 autonomy, no action execution) · no fine-tuning, hosted frontier VLM only · batch overnight ingestion, no streaming · single tenant · one language pair · no handwriting · no entity graph.

### Build vs. buy

Buy the VLM/LLM, the vector store, the object store. **Build the orchestration, the extraction schemas, the validators, the eval harness and the evidence UI.** The differentiator is the trust layer, not the model — models will keep improving underneath us, and we want to be able to swap them without redesigning the system. Everything model-specific sits behind one interface for exactly this reason.

### Hypotheses we want to validate as early as possible

- **H1** — A frontier VLM reading page images outperforms OCR + text-LLM on *our* real layouts. Tested with a 50-document bake-off on day one; it decides the whole perception strategy.
- **H2** — Citations and visible abstention are what buy ops trust, more than a few points of accuracy.
- **H3** — Real questions are mostly lookups, so the cheap structured path carries the volume and the unit economics work.
- **H4** — Cost per document is acceptable at production volume.

### Trade-offs we accept for now

Re-ingestion on schema change; staleness between batches; higher cost per hard query than a pure text pipeline; English/Spanish only; no handwriting.

### Biggest uncertainty

Not model capability — **numeric precision under regulatory scrutiny.** A single wrong amount costs more trust than fifty correct answers earn. Which is why groundedness is the first metric we instrument and the gate we refuse to lower.

### What would have to be true to justify evolving this

- Groundedness ≥ 95% with zero ungrounded numerics on the golden set.
- Field accuracy beating the current manual baseline at lower cost per document.
- Ops genuinely preferring an abstention to a guess.
- Cost per query inside the envelope at real volume.

### Then phase 2

L2 action layer (propose → human confirms → logged) · cross-document reasoning over an entity graph · feedback-driven active learning from the review queue · a distilled small model for high-volume document types to cut unit cost · multi-tenant isolation · broader language coverage.

---

`Pixels → Understanding → Reasoning → Evidence → Action`

**The system's job is not to sound right. It is to show you where it read it.**
