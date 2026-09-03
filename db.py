"""
SQLite warehouse for Poultrix data (all farms, current + historical).

Zero external dependencies (stdlib sqlite3). Central store the collector upserts
into and the API reads from.

Schema:
  farms          - one row per farm (by Poultrix id)
  daily_records  - the daily grid rows (mortality/weight/feed per building x date)
  raw_snapshots  - every raw scrape payload (JSON) for reprocessing
  ingest_log     - one row per ingest run
"""
import hashlib
import json
import os
import re
import sqlite3
from datetime import datetime, timezone

DB_PATH = os.environ.get("POULTRIX_DB",
                         os.path.join(os.path.dirname(os.path.abspath(__file__)), "poultrix.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS farms (
    poultrix_id INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    first_seen  TEXT,
    last_seen   TEXT
);
CREATE TABLE IF NOT EXISTS daily_records (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    farm_poultrix_id INTEGER,
    farm_name       TEXT,
    midgar_text     TEXT,
    building        TEXT,
    record_date     TEXT,          -- ISO yyyy-mm-dd
    record_date_raw TEXT,          -- as scraped
    age_text        TEXT,
    gender          TEXT,
    mortality       INTEGER,
    culls           INTEGER,
    weight          REAL,
    water           REAL,
    feed            REAL,
    total_mortality INTEGER,
    cum_mortality   INTEGER,
    std_weight      REAL,
    notes           TEXT,
    row_hash        TEXT,
    scraped_at      TEXT,
    UNIQUE(farm_poultrix_id, midgar_text, building, record_date, gender)
);
CREATE INDEX IF NOT EXISTS ix_daily_farm_date ON daily_records(farm_poultrix_id, record_date);
CREATE INDEX IF NOT EXISTS ix_daily_flock ON daily_records(farm_poultrix_id, midgar_text);
CREATE TABLE IF NOT EXISTS raw_snapshots (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    farm_poultrix_id INTEGER,
    farm_name    TEXT,
    midgar_text  TEXT,
    captured_at  TEXT,
    payload      TEXT
);
CREATE TABLE IF NOT EXISTS ingest_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at      TEXT,
    mode        TEXT,
    farm_poultrix_id INTEGER,
    farm_name   TEXT,
    midgar_text TEXT,
    rows        INTEGER,
    inserted    INTEGER,
    updated     INTEGER,
    errors      TEXT
);
"""

_NUM_KEYS = {"mortality", "culls", "total_mortality", "cum_mortality"}
_FLOAT_KEYS = {"weight", "water", "feed", "std_weight"}


def connect(path=None):
    con = sqlite3.connect(path or DB_PATH)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_date(raw):
    """Poultrix scrapes dd/mm/yy or d/m/yyyy -> ISO yyyy-mm-dd. Returns '' if unparseable."""
    if not raw:
        return ""
    m = re.match(r"\s*(\d{1,2})/(\d{1,2})/(\d{2,4})\s*$", raw)
    if not m:
        return ""
    d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if y < 100:
        y += 2000
    try:
        return datetime(y, mo, d).strftime("%Y-%m-%d")
    except ValueError:
        return ""


def _num(v):
    try:
        return int(str(v).replace(",", "").strip())
    except (ValueError, AttributeError):
        return None


def _flt(v):
    try:
        return float(str(v).replace(",", "").strip())
    except (ValueError, AttributeError):
        return None


def _row_hash(r):
    key = "|".join(str(r.get(k, "")) for k in
                   ("mortality", "culls", "weight", "water", "feed",
                    "total_mortality", "cum_mortality", "std_weight", "notes"))
    return hashlib.sha1(key.encode("utf-8")).hexdigest()


def _normalize(farm_id, farm_name, midgar, r, scraped_at):
    """Turn a scraped row dict into a normalized db record."""
    return {
        "farm_poultrix_id": farm_id,
        "farm_name": farm_name,
        "midgar_text": midgar,
        "building": (r.get("building") or "").strip(),
        "record_date": parse_date(r.get("date")),
        "record_date_raw": r.get("date") or "",
        "age_text": r.get("age") or "",
        "gender": r.get("population") or r.get("gender") or "",
        "mortality": _num(r.get("mortality")),
        "culls": _num(r.get("culls")),
        "weight": _flt(r.get("weight")),
        "water": _flt(r.get("water")),
        "feed": _flt(r.get("feed")),
        "total_mortality": _num(r.get("totalMort")),
        "cum_mortality": _num(r.get("cumMort")),
        "std_weight": _flt(r.get("stdWeight")),
        "notes": r.get("notes") or "",
        "scraped_at": scraped_at,
    }


def upsert_rows(con, farm_id, farm_name, midgar, rows, mode="incremental"):
    """Insert/update daily rows. Returns (inserted, updated, skipped)."""
    scraped_at = _now()
    inserted = updated = skipped = 0
    for raw in rows:
        rec = _normalize(farm_id, farm_name, midgar, raw, scraped_at)
        if not rec["record_date"] or not rec["building"]:
            continue
        rec["row_hash"] = _row_hash(rec)
        cur = con.execute(
            "SELECT id, row_hash FROM daily_records WHERE farm_poultrix_id=? AND "
            "midgar_text=? AND building=? AND record_date=? AND gender=?",
            (farm_id, midgar, rec["building"], rec["record_date"], rec["gender"]))
        existing = cur.fetchone()
        cols = ("farm_poultrix_id,farm_name,midgar_text,building,record_date,record_date_raw,"
                "age_text,gender,mortality,culls,weight,water,feed,total_mortality,"
                "cum_mortality,std_weight,notes,row_hash,scraped_at")
        vals = [rec["farm_poultrix_id"], rec["farm_name"], rec["midgar_text"], rec["building"],
                rec["record_date"], rec["record_date_raw"], rec["age_text"], rec["gender"],
                rec["mortality"], rec["culls"], rec["weight"], rec["water"], rec["feed"],
                rec["total_mortality"], rec["cum_mortality"], rec["std_weight"],
                rec["notes"], rec["row_hash"], rec["scraped_at"]]
        if existing is None:
            con.execute(f"INSERT INTO daily_records ({cols}) VALUES ({','.join('?'*len(vals))})", vals)
            inserted += 1
        elif existing["row_hash"] != rec["row_hash"]:
            con.execute(
                "UPDATE daily_records SET mortality=?,culls=?,weight=?,water=?,feed=?,"
                "total_mortality=?,cum_mortality=?,std_weight=?,notes=?,row_hash=?,scraped_at=?,"
                "record_date_raw=?,age_text=? WHERE id=?",
                (rec["mortality"], rec["culls"], rec["weight"], rec["water"], rec["feed"],
                 rec["total_mortality"], rec["cum_mortality"], rec["std_weight"], rec["notes"],
                 rec["row_hash"], rec["scraped_at"], rec["record_date_raw"], rec["age_text"],
                 existing["id"]))
            updated += 1
        else:
            skipped += 1

    if farm_id is not None:
        con.execute(
            "INSERT INTO farms (poultrix_id,name,first_seen,last_seen) VALUES (?,?,?,?) "
            "ON CONFLICT(poultrix_id) DO UPDATE SET name=excluded.name, last_seen=excluded.last_seen",
            (farm_id, farm_name, scraped_at, scraped_at))
    con.execute(
        "INSERT INTO ingest_log (run_at,mode,farm_poultrix_id,farm_name,midgar_text,rows,inserted,updated,errors) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (scraped_at, mode, farm_id, farm_name, midgar, len(rows), inserted, updated, None))
    con.commit()
    return inserted, updated, skipped


def save_raw(con, farm_id, farm_name, midgar, payload):
    con.execute(
        "INSERT INTO raw_snapshots (farm_poultrix_id,farm_name,midgar_text,captured_at,payload) "
        "VALUES (?,?,?,?,?)",
        (farm_id, farm_name, midgar, _now(), json.dumps(payload, ensure_ascii=False)))
    con.commit()
