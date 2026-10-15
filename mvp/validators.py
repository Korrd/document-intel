#!/usr/bin/env python3
"""Deterministic validators. No model involved, by design.

The design doc's rule: "if a rule can do it, a model must not". These are the
rules. They are what catch the failure mode a text-level check cannot see --
a single transposed digit in an IBAN or an amount.
"""
import datetime
import re

_IBAN_LEN = {"ES": 24, "PT": 25, "FR": 27, "DE": 22, "IT": 27, "NL": 18,
             "GB": 22, "CH": 21, "BE": 16, "IE": 22, "AT": 20, "LU": 20}
_NIF_LETTERS = "TRWAGMYFPDXBNJZSQVHLCKE"


def _digits(s):
    return re.sub(r"[^0-9]", "", s or "")


def iban_mod97(iban):
    """ISO 13616 / ISO 7064 mod-97-10. Returns (ok, detail)."""
    s = re.sub(r"\s+", "", (iban or "")).upper()
    if not re.fullmatch(r"[A-Z]{2}[0-9A-Z]{10,32}", s):
        return False, "malformed IBAN"
    expect = _IBAN_LEN.get(s[:2])
    if expect and len(s) != expect:
        return False, "length %d, expected %d for %s" % (len(s), expect, s[:2])
    rearranged = s[4:] + s[:4]
    num = "".join(str(ord(c) - 55) if c.isalpha() else c for c in rearranged)
    rem = 0
    for ch in num:                      # streaming mod to avoid a huge int
        rem = (rem * 10 + int(ch)) % 97
    return (rem == 1), ("mod-97 checksum %s" % ("valid" if rem == 1 else "FAILED"))


def spanish_nif(nif):
    """DNI/NIF control letter. Returns (ok, detail)."""
    s = re.sub(r"[\s-]", "", (nif or "")).upper()
    m = re.fullmatch(r"([0-9]{8})([A-Z])", s)
    if m:
        expected = _NIF_LETTERS[int(m.group(1)) % 23]
        ok = expected == m.group(2)
        return ok, "control letter %s (expected %s)" % ("valid" if ok else "FAILED", expected)
    m = re.fullmatch(r"([XYZ])([0-9]{7})([A-Z])", s)        # NIE
    if m:
        pre = {"X": "0", "Y": "1", "Z": "2"}[m.group(1)]
        expected = _NIF_LETTERS[int(pre + m.group(2)) % 23]
        ok = expected == m.group(3)
        return ok, "NIE control letter %s (expected %s)" % ("valid" if ok else "FAILED", expected)
    return False, "not a recognised NIF/NIE format"


def parse_amount(value):
    """Parse a European-formatted amount. Returns float or None.

    Handles '1.284,36', '1,284.36', '245000', '116,25 EUR', '(42,00)'.
    """
    if isinstance(value, (int, float)):
        return float(value)
    if not value:
        return None
    s = str(value).strip()
    neg = s.startswith("(") and s.endswith(")")
    s = re.sub(r"[^0-9,.\-]", "", s)
    if not s:
        return None
    if "," in s and "." in s:
        # whichever separator comes last is the decimal one
        dec = "," if s.rfind(",") > s.rfind(".") else "."
        thou = "." if dec == "," else ","
        s = s.replace(thou, "").replace(dec, ".")
    elif "," in s:
        head, _, tail = s.rpartition(",")
        s = (head.replace(",", "") + "." + tail) if len(tail) in (1, 2) \
            else s.replace(",", "")
    try:
        out = float(s)
    except ValueError:
        return None
    return -out if neg else out


def parse_date(value):
    """Parse a date into ISO form. Returns str or None."""
    if not value:
        return None
    s = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y/%m/%d"):
        try:
            return datetime.datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def reconcile(opening, debit, credit, closing, tol=0.01):
    """opening - debit + credit == closing. Returns (ok, detail)."""
    vals = [parse_amount(v) for v in (opening, debit, credit, closing)]
    if any(v is None for v in vals):
        return None, "insufficient data to reconcile"
    o, d, c, cl = vals
    got = o - d + c
    delta = abs(got - cl)
    if delta <= tol:
        return True, "balance reconciles: %.2f - %.2f + %.2f = %.2f" % (o, d, c, cl)
    return False, ("balance does NOT reconcile: %.2f - %.2f + %.2f = %.2f, "
                   "stated %.2f (delta %.2f)" % (o, d, c, got, cl, delta))


# field name -> (validator, kind)
_FIELD_RULES = {
    "iban": (iban_mod97, "iban_mod97"),
    "account_iban": (iban_mod97, "iban_mod97"),
    "charge_account_iban": (iban_mod97, "iban_mod97"),
    "nif": (spanish_nif, "nif_control_letter"),
    "borrower_nif": (spanish_nif, "nif_control_letter"),
    "holder_nif": (spanish_nif, "nif_control_letter"),
}


def validate_document(fields, doc_type=None):
    """Run every applicable rule over an extracted field dict.

    `fields` maps name -> {"value": ..., "confidence": ...}.
    Returns a list of {check, field, ok, detail, severity}.
    """
    out = []

    def val(name):
        f = fields.get(name)
        return f.get("value") if isinstance(f, dict) else f

    for name, f in sorted(fields.items()):
        rule = _FIELD_RULES.get(name)
        if not rule:
            continue
        fn, kind = rule
        ok, detail = fn(val(name))
        out.append(dict(check=kind, field=name, ok=bool(ok), detail=detail,
                        severity="blocking" if not ok else "info"))

    # amounts must be parseable numbers
    for name, f in sorted(fields.items()):
        if not re.search(r"(amount|balance|total|payment|principal|fee|value|cuota)", name):
            continue
        v = val(name)
        if v in (None, "") or isinstance(v, bool):
            continue
        if "%" in str(v):
            # Composite or rate-bearing value, e.g. "0,50% (1.225,00 EUR)".
            # Not a pure amount, so the pure-amount rule does not apply.
            continue
        if parse_amount(v) is None:
            out.append(dict(check="amount_parseable", field=name, ok=False,
                            detail="cannot parse %r as an amount" % v, severity="blocking"))

    # dates must be parseable
    for name, f in sorted(fields.items()):
        if "date" not in name and not name.endswith(("_start", "_end")):
            continue
        v = val(name)
        if v in (None, ""):
            continue
        if parse_date(v) is None:
            out.append(dict(check="date_parseable", field=name, ok=False,
                            detail="cannot parse %r as a date" % v, severity="warning"))

    # statement arithmetic must close
    if doc_type == "bank_statement" or any(k in fields for k in ("opening_balance", "closing_balance")):
        ok, detail = reconcile(val("opening_balance"), val("total_debit"),
                               val("total_credit"), val("closing_balance"))
        if ok is not None:
            out.append(dict(check="balance_reconciliation", field="closing_balance",
                            ok=bool(ok), detail=detail,
                            severity="blocking" if not ok else "info"))

    # low-confidence fields are flagged for review, not rejected
    for name, f in sorted(fields.items()):
        if isinstance(f, dict) and isinstance(f.get("confidence"), (int, float)) \
                and f["confidence"] < 0.75:
            out.append(dict(check="confidence_threshold", field=name, ok=False,
                            detail="confidence %.2f below threshold 0.75" % f["confidence"],
                            severity="review"))
    return out


def cross_document_checks(docs):
    """Compare shared fields across documents. This is what catches the deed /
    contract payment mismatch in the demo.

    `docs` is a list of (doc_id, doc_type, fields).
    """
    comparable = ["principal", "monthly_payment", "term_months", "nif",
                  "borrower", "iban", "borrower_nif"]
    index = {}
    for doc_id, doc_type, fields in docs:
        for name in comparable:
            f = fields.get(name)
            if not f:
                continue
            v = f.get("value") if isinstance(f, dict) else f
            if v in (None, ""):
                continue
            num = parse_amount(v) if re.search(r"(principal|payment|months)", name) else None
            key = ("%.2f" % num) if num is not None else str(v).strip().upper()
            index.setdefault(name, []).append((doc_id, key, v))

    findings = []
    for name, entries in sorted(index.items()):
        if len(entries) < 2:
            continue
        distinct = {k for _, k, _ in entries}
        if len(distinct) == 1:
            findings.append(dict(check="cross_document_consistency", field=name, ok=True,
                                 detail="%s agrees across %d documents" % (name, len(entries)),
                                 documents=[d for d, _, _ in entries], severity="info"))
        else:
            findings.append(dict(
                check="cross_document_consistency", field=name, ok=False,
                detail="%s DISAGREES across documents: %s" % (
                    name, "; ".join("%s=%s" % (d, v) for d, _, v in entries)),
                documents=[d for d, _, _ in entries], severity="blocking"))
    return findings


if __name__ == "__main__":
    print(iban_mod97("ES9121000418450200051332"))
    print(iban_mod97("ES9121000418450200051333"))
    print(spanish_nif("52410887N"))
    print(parse_amount("1.284,36"), parse_amount("245.000,00"), parse_amount("116,25 EUR"))
    print(reconcile("4.655,45", "2.690,89", "3.426,22", "5.390,78"))
