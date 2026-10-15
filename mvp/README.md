# MVP — Document Intelligence Assistant

A working slice of the design in [`../DESIGN.md`](../DESIGN.md). It ingests scanned
banking/legal documents, answers questions about them, and **shows you the pixels it
read the answer from** — or refuses to answer.

```bash
./run.sh            # render docs, ingest, open the UI
./run.sh --reset    # from scratch
./run.sh --eval     # run the evaluation suite
```

Requires `build-cli login` (the Roche AI Gateway supplies the models) and macOS
(uses `sips` for imaging and Chrome to render the demo documents). **No pip
installs** — everything else is the Python standard library.

## What it actually does

**Ingestion plane** (`pipeline.py`), once per document:

| Stage | Module | Model? |
|---|---|---|
| Intake — normalize, sha256 dedupe, dimensions, quality score | `imaging.py` | no |
| Vision agent — blocks, reading order, tables, bboxes, stamps/signatures | `pipeline.py` | yes |
| Classify — rules first, model guess as fallback | `pipeline.py` | no |
| Extractor agent — per-type schema, per-field confidence + provenance | `pipeline.py` | yes |
| Validators — IBAN mod-97, NIF control letter, balance reconciliation, thresholds | `validators.py` | **no** |
| Stores — page images, JSON record, SQLite field store + block index | `store.py` | no |

**Query plane** (`query.py`), per question:

```
orchestrator plan (intent: lookup|aggregate|compare|infer|act)
  ├─ field_lookup   exact SQL over extracted fields      ← cheap, cannot hallucinate
  ├─ search         BM25 over blocks, citable with bboxes
  ├─ pixel_reread   crops the cited region, re-reads with a stronger model
  └─ compute        AST calculator — the model never does arithmetic
      → synthesizer (answer + per-claim citations)
      → verifier (claim-level grounding gate)
      → answer · answer with caveat · abstain + human review task
```

## The five things worth demoing

| Ask | What it proves |
|---|---|
| "¿Cuál es el IBAN de la cuenta del extracto?" | Structured path: exact field, cited, cheap |
| "¿Existe penalización por amortización anticipada?" | Clause reasoning over prose, not a field lookup |
| "¿Coincide la cuota mensual entre el contrato y la escritura?" | **Finds a planted cross-document defect** (1.248,36 vs 1.284,36) and computes the delta with a calculator |
| "¿Cuál fue el total de comisiones del periodo?" | Aggregation grounded in a table |
| "¿Cuál es el número de teléfono de la titular?" | **Abstains.** Not in the documents, so no answer |

Click any claim in the UI to see the exact region of the page highlighted.

## Deliberate simplifications

Retrieval is BM25 only (no embeddings or reranker yet) · single page per document ·
read-only, L0 autonomy — nothing is ever executed · SQLite rather than a real field
store · one tenant, no ACLs wired in · demo documents are synthetic, with ground
truth declared in `make_demo_docs.py` so the eval set is derived rather than
hand-typed.

## Files

```
make_demo_docs.py   synthetic scanned docs + declared ground truth
gateway.py          Anthropic Messages client over the Roche gateway (stdlib)
imaging.py          hash, dimensions, quality score, bbox cropping
validators.py       the deterministic rules (IBAN, NIF, amounts, reconciliation)
pipeline.py         the ingestion plane
store.py            stores + BM25 retrieval
query.py            the query plane (plan → tools → synthesize → verify)
app.py              stdlib HTTP server
static/index.html   evidence-viewer UI
eval_run.py         field-extraction + golden Q&A suites
```

Cost is tracked per call and shown in the UI — roughly $0.08 per document ingested
and $0.02–0.04 per question at the time of writing.
