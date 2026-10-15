#!/usr/bin/env python3
"""Storage and retrieval.

Three stores, matching the design doc:
  - page images on disk            (the pixels, never discarded)
  - Document Intelligence Records  (JSON: text, blocks, tables, fields, bboxes)
  - a field store + block index    (SQLite: exact lookup, aggregation, search)

Retrieval is BM25 over blocks. The design calls for hybrid (BM25 + embeddings +
rerank); the MVP deliberately ships lexical-only -- it is the honest
simplification, and on this corpus it is already strong because the questions
share vocabulary with the documents. Embeddings are a phase-2 item.
"""
import json
import math
import pathlib
import re
import sqlite3
import time
import unicodedata

ROOT = pathlib.Path(__file__).resolve().parent
DATA = ROOT / "data"
DIRS = DATA / "records"
PAGES = DATA / "pages"
DB_PATH = DATA / "index.sqlite"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
  doc_id TEXT PRIMARY KEY, name TEXT, doc_type TEXT, language TEXT,
  sha256 TEXT UNIQUE, image TEXT, width INT, height INT,
  quality REAL, ingested_at REAL, record TEXT
);
CREATE TABLE IF NOT EXISTS fields (
  doc_id TEXT, name TEXT, value TEXT, numeric REAL, confidence REAL,
  bbox TEXT, block_ids TEXT, source_text TEXT,
  PRIMARY KEY (doc_id, name)
);
CREATE TABLE IF NOT EXISTS blocks (
  doc_id TEXT, block_id TEXT, kind TEXT, text TEXT, bbox TEXT, page INT,
  PRIMARY KEY (doc_id, block_id)
);
CREATE TABLE IF NOT EXISTS validations (
  doc_id TEXT, check_name TEXT, field TEXT, ok INT, detail TEXT, severity TEXT
);
CREATE INDEX IF NOT EXISTS idx_fields_name ON fields(name);
CREATE INDEX IF NOT EXISTS idx_blocks_doc ON blocks(doc_id);
"""

_STOP = set("""de la el los las un una y o en del al a con por para que se su sus
es son the of and to in for on at is are this that be as by or an from with
cual cuales que donde cuando como cuanto cuanta cuantos cuantas""".split())


def connect():
    DATA.mkdir(parents=True, exist_ok=True)
    DIRS.mkdir(parents=True, exist_ok=True)
    PAGES.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    con.executescript(_SCHEMA)
    return con


def tokenize(text):
    text = unicodedata.normalize("NFKD", (text or "").lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return [t for t in re.findall(r"[a-z0-9]+", text) if t not in _STOP and len(t) > 1]


# ------------------------------------------------------------------ writing ---
def already_ingested(con, sha):
    row = con.execute("SELECT doc_id FROM documents WHERE sha256=?", (sha,)).fetchone()
    return row["doc_id"] if row else None


def save_record(record):
    """Persist a Document Intelligence Record and index it."""
    from validators import parse_amount

    con = connect()
    doc_id = record["doc_id"]
    (DIRS / ("%s.json" % doc_id)).write_text(
        json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")

    with con:
        con.execute("DELETE FROM documents WHERE doc_id=?", (doc_id,))
        con.execute("DELETE FROM fields WHERE doc_id=?", (doc_id,))
        con.execute("DELETE FROM blocks WHERE doc_id=?", (doc_id,))
        con.execute("DELETE FROM validations WHERE doc_id=?", (doc_id,))
        con.execute(
            "INSERT INTO documents VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (doc_id, record.get("name"), record.get("doc_type"), record.get("language"),
             record.get("sha256"), record.get("image"),
             record.get("quality", {}).get("width"),
             record.get("quality", {}).get("height"),
             record.get("quality", {}).get("score"), time.time(),
             json.dumps(record, ensure_ascii=False)))
        for name, f in (record.get("fields") or {}).items():
            con.execute(
                "INSERT OR REPLACE INTO fields VALUES (?,?,?,?,?,?,?,?)",
                (doc_id, name, None if f.get("value") is None else str(f.get("value")),
                 parse_amount(f.get("value")), f.get("confidence"),
                 json.dumps(f.get("bbox")), json.dumps(f.get("block_ids")),
                 f.get("source_text")))
        for b in (record.get("blocks") or []):
            con.execute("INSERT OR REPLACE INTO blocks VALUES (?,?,?,?,?,?)",
                        (doc_id, b.get("id"), b.get("kind"), b.get("text"),
                         json.dumps(b.get("bbox")), b.get("page", 1)))
        for v in (record.get("validations") or []):
            con.execute("INSERT INTO validations VALUES (?,?,?,?,?,?)",
                        (doc_id, v.get("check"), v.get("field"), int(bool(v.get("ok"))),
                         v.get("detail"), v.get("severity")))
    con.close()
    return doc_id


# ------------------------------------------------------------------ reading ---
def list_documents():
    con = connect()
    rows = con.execute(
        "SELECT doc_id, name, doc_type, language, image, width, height, quality,"
        " ingested_at FROM documents ORDER BY ingested_at").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["fields"] = con.execute(
            "SELECT COUNT(*) c FROM fields WHERE doc_id=?", (r["doc_id"],)).fetchone()["c"]
        d["failed_checks"] = con.execute(
            "SELECT COUNT(*) c FROM validations WHERE doc_id=? AND ok=0",
            (r["doc_id"],)).fetchone()["c"]
        out.append(d)
    con.close()
    return out


def get_record(doc_id):
    con = connect()
    row = con.execute("SELECT record FROM documents WHERE doc_id=?", (doc_id,)).fetchone()
    con.close()
    return json.loads(row["record"]) if row else None


def all_records():
    con = connect()
    rows = con.execute("SELECT record FROM documents ORDER BY ingested_at").fetchall()
    con.close()
    return [json.loads(r["record"]) for r in rows]


def field_lookup(names=None, doc_ids=None):
    """Exact structured lookup -- the cheap path. No model, no hallucination."""
    con = connect()
    sql = ("SELECT f.doc_id, d.name AS doc_name, d.doc_type, f.name, f.value, f.numeric,"
           " f.confidence, f.bbox, f.block_ids, f.source_text"
           " FROM fields f JOIN documents d ON d.doc_id=f.doc_id")
    where, args = [], []
    if names:
        where.append("f.name IN (%s)" % ",".join("?" * len(names)))
        args += list(names)
    if doc_ids:
        where.append("f.doc_id IN (%s)" % ",".join("?" * len(doc_ids)))
        args += list(doc_ids)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY f.doc_id, f.name"
    rows = [dict(r) for r in con.execute(sql, args).fetchall()]
    con.close()
    for r in rows:
        r["bbox"] = json.loads(r["bbox"]) if r["bbox"] else None
        r["block_ids"] = json.loads(r["block_ids"]) if r["block_ids"] else None
    return rows


def field_names():
    con = connect()
    rows = con.execute("SELECT DISTINCT name FROM fields ORDER BY name").fetchall()
    con.close()
    return [r["name"] for r in rows]


def validations(doc_id=None):
    con = connect()
    if doc_id:
        rows = con.execute("SELECT * FROM validations WHERE doc_id=?", (doc_id,)).fetchall()
    else:
        rows = con.execute("SELECT * FROM validations").fetchall()
    con.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------- retrieval ---
def search(query, k=6, doc_ids=None):
    """BM25 over blocks. Returns ranked evidence with bbox so it stays citable."""
    con = connect()
    sql = "SELECT doc_id, block_id, kind, text, bbox, page FROM blocks"
    args = []
    if doc_ids:
        sql += " WHERE doc_id IN (%s)" % ",".join("?" * len(doc_ids))
        args = list(doc_ids)
    blocks = [dict(r) for r in con.execute(sql, args).fetchall()]
    names = {r["doc_id"]: r["name"] for r in
             con.execute("SELECT doc_id, name FROM documents").fetchall()}
    con.close()
    if not blocks:
        return []

    q = tokenize(query)
    if not q:
        return []
    docs_tokens = [tokenize(b["text"]) for b in blocks]
    N = len(blocks)
    avgdl = sum(len(t) for t in docs_tokens) / N or 1.0
    df = {}
    for toks in docs_tokens:
        for t in set(toks):
            df[t] = df.get(t, 0) + 1

    k1, b_ = 1.5, 0.75
    scored = []
    for blk, toks in zip(blocks, docs_tokens):
        if not toks:
            continue
        tf = {}
        for t in toks:
            tf[t] = tf.get(t, 0) + 1
        score = 0.0
        for t in q:
            if t not in tf:
                continue
            idf = math.log(1 + (N - df[t] + 0.5) / (df[t] + 0.5))
            score += idf * (tf[t] * (k1 + 1)) / (tf[t] + k1 * (1 - b_ + b_ * len(toks) / avgdl))
        if score > 0:
            scored.append((score, blk))

    scored.sort(key=lambda s: -s[0])
    out = []
    for score, blk in scored[:k]:
        out.append(dict(doc_id=blk["doc_id"], doc_name=names.get(blk["doc_id"]),
                        block_id=blk["block_id"], kind=blk["kind"],
                        text=blk["text"], page=blk["page"],
                        bbox=json.loads(blk["bbox"]) if blk["bbox"] else None,
                        score=round(score, 3)))
    return out


def blocks_by_id(doc_id, block_ids):
    if not block_ids:
        return []
    con = connect()
    rows = con.execute(
        "SELECT doc_id, block_id, kind, text, bbox, page FROM blocks"
        " WHERE doc_id=? AND block_id IN (%s)" % ",".join("?" * len(block_ids)),
        [doc_id] + list(block_ids)).fetchall()
    con.close()
    out = []
    for r in rows:
        d = dict(r)
        d["bbox"] = json.loads(d["bbox"]) if d["bbox"] else None
        out.append(d)
    return out


def reset():
    for p in (DB_PATH,):
        if p.exists():
            p.unlink()
    for d in (DIRS,):
        if d.exists():
            for f in d.glob("*.json"):
                f.unlink()


def union_bbox(boxes):
    boxes = [b for b in boxes if b and len(b) == 4]
    if not boxes:
        return None
    return [min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes)]
