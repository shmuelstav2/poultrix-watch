"""Tests for db.py — run: python3 test_db.py  (also pytest-compatible)."""
import os
import tempfile

import db

SAMPLE = [
    {"date": "24/08/26", "building": "1", "age": "W:33:5", "population": "מעורב",
     "mortality": "49", "culls": "0", "weight": "0", "feed": "0", "totalMort": "49",
     "cumMort": "0", "stdWeight": "2075", "notes": ""},
    {"date": "3/9/2026", "building": "2", "age": "W:35:5", "population": "זכר",
     "mortality": "100", "culls": "2", "weight": "0", "feed": "0", "totalMort": "100",
     "cumMort": "1294", "stdWeight": "2423", "notes": "test"},
]


def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.remove(path)
    return db.connect(path), path


def test_parse_date():
    assert db.parse_date("24/08/26") == "2026-08-24"
    assert db.parse_date("3/9/2026") == "2026-09-03"
    assert db.parse_date("1/9/2026") == "2026-09-01"
    assert db.parse_date("") == ""
    assert db.parse_date("garbage") == ""
    print("ok parse_date")


def test_num_flt():
    assert db._num("1,294") == 1294
    assert db._num("") is None
    assert db._flt("2,075") == 2075.0
    assert db._flt("x") is None
    print("ok num/flt")


def test_insert_then_idempotent():
    con, path = _fresh_db()
    try:
        ins, upd, skip = db.upsert_rows(con, 482, "כפר הריף", "4-2026", SAMPLE)
        assert (ins, upd, skip) == (2, 0, 0), (ins, upd, skip)
        # re-run identical -> all skipped
        ins, upd, skip = db.upsert_rows(con, 482, "כפר הריף", "4-2026", SAMPLE)
        assert (ins, upd, skip) == (0, 0, 2), (ins, upd, skip)
        # change one value -> 1 update
        changed = [dict(SAMPLE[0]), dict(SAMPLE[1])]
        changed[0]["mortality"] = "55"
        ins, upd, skip = db.upsert_rows(con, 482, "כפר הריף", "4-2026", changed)
        assert (ins, upd, skip) == (0, 1, 1), (ins, upd, skip)
        # verify stored + normalized
        row = con.execute("SELECT * FROM daily_records WHERE building='1'").fetchone()
        assert row["record_date"] == "2026-08-24"
        assert row["mortality"] == 55
        assert row["farm_name"] == "כפר הריף"
        # farms table populated
        assert con.execute("SELECT COUNT(*) FROM farms").fetchone()[0] == 1
        # ingest_log has entries
        assert con.execute("SELECT COUNT(*) FROM ingest_log").fetchone()[0] == 3
        print("ok insert/idempotent/update")
    finally:
        con.close()
        os.remove(path)


def test_bad_rows_skipped():
    con, path = _fresh_db()
    try:
        bad = [{"date": "", "building": "1", "mortality": "5"},      # no date
               {"date": "24/08/26", "building": "", "mortality": "5"}]  # no building
        ins, upd, skip = db.upsert_rows(con, 1, "t", "f", bad)
        assert ins == 0, ins
        print("ok bad rows skipped")
    finally:
        con.close()
        os.remove(path)


if __name__ == "__main__":
    test_parse_date()
    test_num_flt()
    test_insert_then_idempotent()
    test_bad_rows_skipped()
    print("\nALL TESTS PASSED")
