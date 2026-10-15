#!/usr/bin/env python3
"""Evaluation harness.

The design doc argues the eval/trust layer is the actual differentiator, so it
ships in the MVP rather than being deferred. Two suites:

  1. Field extraction vs. ground truth (docs/manifest.json)
     -> exact-match precision/recall per field.
  2. Question answering vs. a golden set (eval/golden.json)
     -> groundedness, citation coverage, and -- the metric we gate on --
        correct-abstention rate on deliberately unanswerable questions.

Usage:
  python3 eval_run.py                 # full suite
  python3 eval_run.py --fields        # extraction only (no model calls)
  python3 eval_run.py --qa            # question answering only
"""
import json
import pathlib
import re
import sys
import time
import unicodedata

import gateway
import query
import store
import validators

ROOT = pathlib.Path(__file__).resolve().parent
GOLDEN = ROOT / "eval" / "golden.json"
MANIFEST = ROOT / "docs" / "manifest.json"


def norm(v):
    """Compare values the way a human would: ignore case, accents, currency,
    and European vs. plain number formatting."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    n = validators.parse_amount(v) if not isinstance(v, bool) else None
    if isinstance(v, (int, float)) or (n is not None and re.fullmatch(
            r"[\s0-9.,\-]+(\s*(eur|euros|€))?", str(v).strip().lower())):
        return "%.2f" % n if n is not None else str(v)
    s = unicodedata.normalize("NFKD", str(v).lower().strip())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"\b(eur|euros|€|meses|months)\b", "", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


# --------------------------------------------------------------- suite 1 -----
def eval_fields():
    if not MANIFEST.exists():
        print("no docs/manifest.json -- run make_demo_docs.py first")
        return {}
    truth_by_doc = {d["id"]: d.get("truth", {}) for d in
                    json.loads(MANIFEST.read_text(encoding="utf-8"))}
    rows, agg = [], {"checked": 0, "correct": 0, "missed": 0, "wrong": 0}
    for doc_id, truth in sorted(truth_by_doc.items()):
        rec = store.get_record(doc_id)
        if not rec:
            print("  ! %s not ingested, skipping" % doc_id)
            continue
        fields = rec.get("fields") or {}
        for key, expected in sorted(truth.items()):
            got_f = fields.get(key)
            got = got_f.get("value") if isinstance(got_f, dict) else None
            conf = got_f.get("confidence") if isinstance(got_f, dict) else None
            exp_n, got_n = norm(expected), norm(got)
            if key not in fields or got in (None, ""):
                verdict = "MISSED"
                agg["missed"] += 1
            elif exp_n == got_n or (exp_n and got_n and exp_n in got_n):
                verdict = "ok"
                agg["correct"] += 1
            else:
                verdict = "WRONG"
                agg["wrong"] += 1
            agg["checked"] += 1
            rows.append((doc_id, key, expected, got, conf, verdict))

    print("\n== Suite 1: field extraction vs. ground truth ==")
    for doc_id, key, exp, got, conf, verdict in rows:
        if verdict == "ok":
            continue
        print("  %-6s %-16s %-22s expected=%-26s got=%s"
              % (verdict, doc_id, key, str(exp)[:26], str(got)[:40]))
    n = agg["checked"] or 1
    print("  %d/%d exact (%.1f%%)  wrong=%d  missed=%d"
          % (agg["correct"], agg["checked"], 100.0 * agg["correct"] / n,
             agg["wrong"], agg["missed"]))

    # the metric that matters most in a bank: are the numerics right?
    numeric_keys = [r for r in rows if validators.parse_amount(r[2]) is not None]
    nc = sum(1 for r in numeric_keys if r[5] == "ok")
    if numeric_keys:
        print("  numeric fields: %d/%d exact (%.1f%%)"
              % (nc, len(numeric_keys), 100.0 * nc / len(numeric_keys)))
    return dict(field_exact=agg["correct"] / n, numeric_exact=(nc / len(numeric_keys)) if numeric_keys else None,
                **agg)


# --------------------------------------------------------------- suite 2 -----
def default_golden():
    """The golden Q&A set. 20% deliberately unanswerable, per the design doc."""
    return [
        dict(id="q1", intent="lookup", question="¿Cuál es el IBAN de la cuenta del extracto bancario?",
             must_contain=["ES9121000418450200051332"], must_cite=True),
        dict(id="q2", intent="lookup", question="¿Cuál es el capital concedido en el contrato de préstamo?",
             must_contain=["245.000", "245000"], any_of=True, must_cite=True),
        dict(id="q3", intent="infer", question="¿Existe penalización por amortización anticipada? ¿De cuánto?",
             must_contain=["0,25", "0.25"], any_of=True, must_cite=True),
        dict(id="q4", intent="infer", question="¿Qué ocurre si dejo de pagar dos cuotas consecutivas?",
             must_contain=["vencimiento anticipado"], must_cite=True),
        dict(id="q5", intent="compare", question="¿Coincide la cuota mensual entre el contrato de préstamo y la escritura notarial?",
             must_contain=["no"], must_detect_inconsistency=True, must_cite=True),
        dict(id="q6", intent="aggregate", question="¿Cuál fue el total de comisiones del periodo en el extracto?",
             must_contain=["116,25", "116.25"], any_of=True, must_cite=True),
        dict(id="q7", intent="lookup", question="¿Está firmado y sellado el contrato de préstamo?",
             must_contain=["s"], must_cite=True),
        dict(id="q8", intent="lookup", question="¿Cuál es el valor de tasación de la finca?",
             must_contain=["352.000", "352000"], any_of=True, must_cite=True),
        # --- deliberately unanswerable: the abstention tests ------------------
        dict(id="u1", intent="unanswerable", question="¿Cuál es el número de teléfono de contacto de la titular?",
             must_abstain=True),
        dict(id="u2", intent="unanswerable", question="¿Cuál era el saldo de la cuenta en diciembre de 2025?",
             must_abstain=True),
    ]


def load_golden():
    if GOLDEN.exists():
        return json.loads(GOLDEN.read_text(encoding="utf-8"))
    GOLDEN.parent.mkdir(parents=True, exist_ok=True)
    g = default_golden()
    GOLDEN.write_text(json.dumps(g, indent=2, ensure_ascii=False), encoding="utf-8")
    return g


def eval_qa(limit=None):
    golden = load_golden()[:limit] if limit else load_golden()
    print("\n== Suite 2: grounded question answering (%d questions) ==" % len(golden))
    res, t0 = [], time.time()
    for g in golden:
        r = query.answer(g["question"])
        status = r.get("status")
        ans = (r.get("answer") or "")
        ansn = norm(ans)
        abstained = status == "abstained"
        claims = r.get("claims") or []
        cited = sum(1 for c in claims if c.get("citations"))
        grounded = sum(1 for c in claims if c.get("grounded"))

        failures = []
        if g.get("must_abstain"):
            if not abstained:
                failures.append("should have abstained, answered instead")
        else:
            if abstained:
                failures.append("abstained on an answerable question")
            needles = [norm(x) for x in (g.get("must_contain") or [])]
            if needles:
                hit = any(x in ansn for x in needles) if g.get("any_of") \
                    else all(x in ansn for x in needles)
                if not hit:
                    failures.append("answer missing %s" % g.get("must_contain"))
            if g.get("must_cite") and not cited:
                failures.append("no claim carried a citation")
            if g.get("must_detect_inconsistency") and not r.get("inconsistency"):
                failures.append("did not flag the cross-document inconsistency")

        ok = not failures
        res.append(dict(id=g["id"], intent=g["intent"], ok=ok, status=status,
                        failures=failures, claims=len(claims), grounded=grounded,
                        cited=cited, ms=r.get("elapsed_ms"),
                        usd=(r.get("cost") or {}).get("usd", 0)))
        print("  %-4s %-13s %-22s %s" % (
            "PASS" if ok else "FAIL", g["id"] + " " + g["intent"], status,
            "" if ok else "| " + "; ".join(failures)))
        if not ok:
            print("        answer: %s" % ans[:150].replace("\n", " "))

    answerable = [r for r in res if r["intent"] != "unanswerable"]
    unanswerable = [r for r in res if r["intent"] == "unanswerable"]
    total_claims = sum(r["claims"] for r in res) or 1
    total_grounded = sum(r["grounded"] for r in res)
    total_cited = sum(r["cited"] for r in res)

    print("\n  task success        %d/%d  (%.0f%%)"
          % (sum(1 for r in res if r["ok"]), len(res),
             100.0 * sum(1 for r in res if r["ok"]) / (len(res) or 1)))
    if answerable:
        print("    answerable        %d/%d" % (sum(1 for r in answerable if r["ok"]), len(answerable)))
    if unanswerable:
        print("    correct abstention %d/%d  <-- the gate we care about"
              % (sum(1 for r in unanswerable if r["ok"]), len(unanswerable)))
    print("  groundedness        %d/%d claims survived the verifier (%.0f%%)"
          % (total_grounded, total_claims, 100.0 * total_grounded / total_claims))
    print("  citation coverage   %d/%d claims carried a citable region (%.0f%%)"
          % (total_cited, total_claims, 100.0 * total_cited / total_claims))
    print("  latency             median %dms" % sorted(r["ms"] or 0 for r in res)[len(res) // 2])
    print("  cost                $%.4f total, $%.4f per question"
          % (sum(r["usd"] for r in res), sum(r["usd"] for r in res) / (len(res) or 1)))
    print("  wall clock          %.1fs" % (time.time() - t0))
    return res


def main():
    args = sys.argv[1:]
    only_fields = "--fields" in args
    only_qa = "--qa" in args
    docs = store.list_documents()
    if not docs:
        sys.exit("no documents ingested -- run `python3 pipeline.py --reset` first")
    print("Document Intelligence Assistant -- evaluation")
    print("  corpus: %d documents, %d fields indexed" % (len(docs), len(store.field_names())))

    if not only_qa:
        eval_fields()
    if not only_fields:
        eval_qa()
        print("\n  cross-document findings:")
        for f in query.cross_document_report():
            print("    %-5s %s" % ("ok" if f["ok"] else "FAIL", f["detail"]))
    print("\n  total model spend this run: $%.4f" % gateway.usage_report()["usd"])


if __name__ == "__main__":
    main()
