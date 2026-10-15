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

**Medallion layers** — the stores map onto Bronze / Silver / Gold:

| Layer | On disk | Holds |
|---|---|---|
| **Bronze** | `data/pages/*.png` | Page images, sha256, dimensions, quality score — the pixels |
| **Silver** | `data/records/*.json` | Normalized Markdown + blocks + tables, **every one carrying a bbox** |
| **Gold** | `data/index.sqlite` | Validated fields with confidence and provenance; block index for retrieval |

Silver carrying coordinates is the load-bearing detail: a Markdown-only Silver layer severs the link back to Bronze, and citation, visual verification and the pixel re-read all become impossible.

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
EU AI Act pre-flight (policy.py)  ← deterministic; refuses before any model runs
orchestrator plan (intent + complexity → model tier)
  ├─ field_lookup   exact SQL over extracted fields      ← cheap, cannot hallucinate
  ├─ search         BM25 over blocks, citable with bboxes
  ├─ pixel_reread   crops the cited region, re-reads with a stronger model
  └─ compute        AST calculator — the model never does arithmetic
      → synthesizer (answer + per-claim citations)
      → verifier (claim-level grounding gate; fails closed)
      → EU AI Act post-flight (disclosure, minimisation, blocks uncited claims)
      → answer · answer with caveat · abstain + human review task · refused
```

**Model tiering.** The planner rates complexity and that selects the tier: Haiku for trivial/easy, Sonnet for moderate/complex, Opus only for the pixel re-read. Two exceptions on principle — the **verifier always runs on Sonnet** (it's the gate; we don't economise on the gate), and a deterministic floor in `query.py` overrides the planner for `compare`/`aggregate`/`act`, because the planner rated a cross-document comparison "easy", the cheap tier took it, and the verifier dropped one of its claims. Tiering roughly halved cost per question.

**EU AI Act gate** (`policy.py`, no model calls). Art. 5 prohibited inferences are refused at the gate — a refusal costs $0.00 because nothing downstream runs. Annex III uses (creditworthiness, fraud) are classified high-risk and marked advisory-only. Decisional phrasing ("apruébame el préstamo") is reframed as a recommendation under the L1 autonomy ceiling. Art. 14 is enforced rather than disclaimed: an answer whose claims carry no citable region is blocked, because there is nothing for a human to oversee.

## The five things worth demoing

| Ask | What it proves |
|---|---|
| "¿Cuál es el IBAN de la cuenta del extracto?" | Structured path: exact field, cited, cheap |
| "¿Existe penalización por amortización anticipada?" | Clause reasoning over prose, not a field lookup |
| "¿Coincide la cuota mensual entre el contrato y la escritura?" | **Finds a planted cross-document defect** (1.248,36 vs 1.284,36) and computes the delta with a calculator |
| "¿Cuál fue el total de comisiones del periodo?" | Aggregation grounded in a table |
| "¿Cuál es el número de teléfono de la titular?" | **Abstains.** Not in the documents, so no answer |
| "¿Cuál es la etnia de la titular?" | **Refused at the EU AI Act gate** before any model runs — $0.00 |
| "Evalúa la solvencia de la titular…" | Classified **Annex III high-risk**, advisory-only, human confirmation required |

Click any claim in the UI to see the exact region of the page highlighted.

## Measured

`./run.sh --eval` reproduces these:

| | |
|---|---|
| Field extraction, exact match | 31/32 (96.9%) · numerics 24/25 (96.0%) |
| Task success, 13-question golden set | 13/13 |
| Correct abstention | 2/2 |
| EU AI Act gate | 3/3 |
| Citation coverage | 21/21 released claims (100%) |
| Groundedness | 19/21 claims survived the verifier (90%) |
| Latency / cost | ~9s and ~$0.013 per question, cache-cold |

Two caveats to keep in view: a **repeat** eval run reports a ~850ms median because the gateway serves cached responses, so only cache-cold numbers mean anything; and the one remaining field miss is a free-text clause whose ground truth is an English paraphrase of Spanish contract prose, which substring matching cannot fairly judge. Left as a visible miss rather than tuned away.

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
policy.py           the EU AI Act gate (deterministic, no model calls)
pipeline.py         the ingestion plane
store.py            stores + BM25 retrieval
query.py            the query plane (plan → tools → synthesize → verify)
app.py              stdlib HTTP server
static/index.html   evidence-viewer UI
eval_run.py         field-extraction + golden Q&A suites
```

Cost is tracked per call and shown in the UI — roughly $0.08 per document ingested
and $0.02–0.04 per question at the time of writing.
