# Pixels to Action — Multi-Agent Visual Intelligence System

Design submission for the **Accenture × Codemotion workshop at #CodeMeet Barcelona** (15 Oct 2026).

**Challenge:** design a Document Intelligence Assistant for a financial institution that processes banking and legal documentation arriving as scanned images — heterogeneous layouts, tables, variable quality. Users must be able to ask questions and get answers grounded in the documents.

> `Document / Image → Understanding → Reasoning → Answer / Action`

This is a **design** deliverable, not an implementation: the point is the decisions, the trade-offs, and a system that could evolve into a real one.

## Contents

| File | What it is |
|---|---|
| [`DESIGN.md`](./DESIGN.md) | The full written design — scope, capabilities, architecture, trust & controls, MVP |
| [`deck.html`](./deck.html) | 12-slide presentation deck. Open in a browser, `←` `→` to navigate, `F` for fullscreen |

## The design in one minute

- **Two planes.** Ingestion runs once per document (a pipeline). Querying runs many times (agentic, with a planner). Conflating them is the most common mistake in this problem space.
- **We never throw away the pixels.** Every extracted value keeps its page and bounding box. Hard or low-confidence questions crop that exact region and re-read it with a stronger model. The user sees the highlighted crop, not a claim about it.
- **If a rule can do it, a model must not.** Arithmetic, checksums, access control, routing and validation are deterministic. Models handle perception, schema mapping, planning and synthesis.
- **Evidence-first, or no answer.** Every claim is cited to document + page + box; a verifier gates on grounding. Abstention is a success state.
- **Autonomy is a dial.** The MVP ships at L0 — read-only answers with evidence. Irreversible actions are out of scope by design.
- **Build the trust layer, buy the model.** Models improve underneath us; the eval harness, schemas and evidence UI are the differentiator.

## Presenting it

```bash
open deck.html
```

Group number and member names are placeholders in both files — fill them in before sending.
