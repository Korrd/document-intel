#!/usr/bin/env python3
"""EU AI Act policy gate. Deterministic, no model calls.

Adopted from the team's whiteboard design, which put compliance *on the request
path* rather than in a risks appendix. That framing is better than treating it
as documentation, because a gate can refuse and a bullet point cannot.

Every request passes through `preflight` before any model is called, and every
answer passes through `postflight` before release. Both stamp the trace, which
is what Art. 12 record-keeping actually asks for.

Scope note, stated plainly: this is a thin, auditable implementation of the
obligations that bite for a document intelligence assistant in a bank. It is
engineering, not legal advice -- a real deployment needs counsel, a conformity
assessment, and a registered risk-management system under Art. 9.

Why rules and not a model: a compliance gate must be inspectable, replayable
and stable across releases. A model that occasionally refuses differently is
worse than useless here. Same principle as validators.py -- if a rule can do
it, a model must not.
"""
import re

# --- Art. 5: prohibited practices -------------------------------------------
# Inferences this system must never make from a customer's documents, whatever
# the user asks. Refusal, not degradation.
PROHIBITED = [
    ("social_scoring", r"(social scoring|puntuaci[oó]n social|score as a person|"
                       r"trustworthiness as a (person|human)|fiabilidad como persona)"),
    ("special_category_inference",
     r"(etnia|raza|racial|ethnicity|religi[oó]n|religious belief|orientaci[oó]n sexual|"
     r"sexual orientation|afiliaci[oó]n sindical|trade union|opini[oó]n pol[ií]tica|"
     r"political (opinion|view)|estado de salud|health status|discapacidad|disability)"),
    ("emotion_inference", r"(estado emocional|emotional state|infer(ir)? emotions?|"
                          r"sentimiento del (cliente|titular)|how (does|did) .* feel)"),
    ("biometric_categorisation", r"(categorizaci[oó]n biom[eé]trica|biometric categoris|"
                                 r"identify .* from (the )?(signature|handwriting) alone)"),
]

# --- Annex III: high-risk uses ----------------------------------------------
# Not refused -- these are permitted, but they switch on the obligations below.
HIGH_RISK_PURPOSES = [
    ("creditworthiness", r"(solvencia|creditworthin|credit scor|scoring de cr[eé]dito|"
                         r"capacidad de pago|approve .*(loan|cr[eé]dito)|conceder el pr[eé]stamo|"
                         r"deny .*(loan|credit)|denegar .*(pr[eé]stamo|cr[eé]dito))",
     "Annex III(5)(b) — creditworthiness evaluation of natural persons"),
    ("fraud_assessment", r"(fraude|fraud|blanqueo|money launder|aml|sospechos)",
     "Annex III(5) — access to essential private services"),
]

# --- Art. 14: human oversight ----------------------------------------------
# Requests phrased as a decision rather than a question. These are not refused;
# the answer is reframed as a recommendation that a human must confirm.
DECISION_VERBS = (r"\b(aprueba|aprobar|apru[eé]bame|deniega|denegar|rechaza|rechazar|"
                  r"firma|firmar|autoriza|autorizar|ejecuta|ejecutar|paga|pagar|"
                  r"transfiere|transferir|approve|reject|deny|authorise|authorize|"
                  r"execute|sign|pay|transfer|decide|dictamina)\b")

# --- GDPR adjacency: data minimisation -------------------------------------
SPECIAL_CATEGORY_IN_OUTPUT = [
    ("health_data", r"(diagn[oó]stico|historial m[eé]dico|medical record|enfermedad)"),
    ("biometric_data", r"(huella dactilar|fingerprint|reconocimiento facial|facial recognition)"),
]

AUTONOMY_CEILING = "L1"     # extract and answer; never decide, never execute

DISCLOSURE = ("Respuesta generada por un sistema de IA a partir de los documentos "
              "citados. Verifique la evidencia antes de usarla para cualquier "
              "decisión. / AI-generated from the cited documents; verify the "
              "evidence before relying on it for a decision.")


def _hay(text):
    """Lowercase, accent-tolerant haystack. Keeps the rules readable."""
    s = (text or "").lower()
    for a, b in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ñ", "n")):
        s = s.replace(a, b)
    return s


def _match(rules, text):
    hay = _hay(text)
    out = []
    for rule in rules:
        name, pattern = rule[0], rule[1]
        if re.search(pattern, hay) or re.search(pattern, text or "", re.IGNORECASE):
            out.append(rule)
    return out


def preflight(question, purpose_hint=None):
    """Gate a request before any model is called.

    Returns a decision dict. `allowed=False` means nothing downstream runs --
    the question never reaches a model, so a refusal costs nothing.
    """
    articles, obligations, notes = [], [], []

    prohibited = _match(PROHIBITED, question)
    if prohibited:
        return dict(
            allowed=False,
            decision="refused",
            purpose=purpose_hint or "prohibited_inference",
            risk_tier="prohibited",
            articles=["Art. 5 — prohibited AI practices"],
            triggered=[name for name, _ in prohibited],
            obligations=[],
            autonomy_ceiling=AUTONOMY_CEILING,
            reason=("This request asks the system to infer a characteristic it must "
                    "never infer from a customer's documents. Refused at the gate, "
                    "before any model was called."),
            disclosure=DISCLOSURE)

    high_risk = _match(HIGH_RISK_PURPOSES, question)
    purpose = purpose_hint or (high_risk[0][0] if high_risk else "information_retrieval")
    risk_tier = "high" if high_risk else "limited"
    if high_risk:
        articles += [r[2] for r in high_risk]
        obligations += [
            "Art. 9 — risk management system",
            "Art. 10 — data governance over the ingested corpus",
            "Art. 14 — human oversight: output is a recommendation, never a decision",
            "Art. 15 — accuracy, robustness and the published eval metrics",
        ]
        notes.append("High-risk use under Annex III: the answer is advisory only and "
                     "must be confirmed by a competent person.")

    decisional = bool(re.search(DECISION_VERBS, _hay(question)))
    if decisional:
        articles.append("Art. 14 — human oversight")
        obligations.append("Art. 22 GDPR — no solely automated decision with legal effect")
        notes.append("Phrased as a decision. Reframed as a recommendation requiring "
                     "human confirmation; the system's autonomy ceiling is %s."
                     % AUTONOMY_CEILING)

    # Always on, for every request.
    articles.append("Art. 12 — record-keeping (the per-question trace)")
    articles.append("Art. 50 — transparency: AI-generated output is disclosed")

    return dict(
        allowed=True,
        decision="allowed_with_obligations" if (high_risk or decisional) else "allowed",
        purpose=purpose,
        risk_tier=risk_tier,
        articles=articles,
        triggered=[r[0] for r in high_risk] + (["decisional_phrasing"] if decisional else []),
        obligations=obligations,
        requires_human_confirmation=bool(high_risk or decisional),
        autonomy_ceiling=AUTONOMY_CEILING,
        reason=" ".join(notes) or "Routine information retrieval over the ingested corpus.",
        disclosure=DISCLOSURE)


def postflight(decision, answer_text, claims, status):
    """Gate an answer before release. Never rewrites the answer silently --
    it attaches obligations and flags, so the UI and the trace both show them.
    """
    flags = []

    leaked = _match(SPECIAL_CATEGORY_IN_OUTPUT, answer_text or "")
    if leaked:
        flags.append(dict(
            flag="special_category_data_in_output",
            detail="Output references %s. Under data minimisation this should be "
                   "surfaced only to a role entitled to it."
                   % ", ".join(name for name, _ in leaked),
            severity="review"))

    # Art. 14 is not satisfied by a disclaimer: an answer that cites nothing
    # cannot be meaningfully overseen, because there is nothing to check.
    if status in ("answered", "answered_with_caveat"):
        uncited = [c for c in (claims or []) if not c.get("citations")]
        if uncited:
            flags.append(dict(
                flag="uncited_claim_released",
                detail="%d claim(s) carried no citable region, which defeats human "
                       "oversight." % len(uncited),
                severity="blocking"))

    if decision.get("requires_human_confirmation") and status != "abstained":
        flags.append(dict(
            flag="human_confirmation_required",
            detail="High-risk or decisional request: this output is advisory and "
                   "must be confirmed by a competent person before it is acted on.",
            severity="info"))

    return dict(flags=flags,
                disclosure=decision.get("disclosure", DISCLOSURE),
                released=not any(f["severity"] == "blocking" for f in flags),
                articles=decision.get("articles", []),
                obligations=decision.get("obligations", []))


if __name__ == "__main__":
    import json
    for q in ["¿Cuál es el IBAN de la cuenta del extracto?",
              "¿Cuál es la etnia de la titular según los documentos?",
              "Apruébame el préstamo 0098-4471",
              "Evalúa la solvencia de la titular para un nuevo crédito"]:
        d = preflight(q)
        print("\n%s\n  -> %s / %s / tier=%s" % (q, d["decision"], d["purpose"], d["risk_tier"]))
        if d["triggered"]:
            print("     triggered: %s" % d["triggered"])
        print("     %s" % d["reason"])
