"""Tests for api.py — run: python3 test_api.py  (needs fastapi + httpx)."""
import os
import tempfile

# isolated temp DB + known API key BEFORE importing the app
_fd, _path = tempfile.mkstemp(suffix=".db")
os.close(_fd)
os.remove(_path)
os.environ["POULTRIX_DB"] = _path
os.environ["POULTRIX_API_KEY"] = "testkey"

import db  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
import api  # noqa: E402

KEY = {"X-API-Key": "testkey"}
SAMPLE = [
    {"date": "24/08/26", "building": "1", "age": "W:33:5", "population": "מעורב",
     "mortality": "49", "culls": "0", "weight": "0", "feed": "0", "totalMort": "49",
     "cumMort": "1000", "stdWeight": "2075", "notes": ""},
    {"date": "25/08/26", "building": "1", "age": "W:34:5", "population": "מעורב",
     "mortality": "63", "culls": "0", "weight": "1850", "feed": "0", "totalMort": "63",
     "cumMort": "1063", "stdWeight": "2171", "notes": ""},
]


def seed():
    con = db.connect(_path)
    db.upsert_rows(con, 482, "כפר הריף", "4-2026", SAMPLE, mode="backfill")
    con.close()


def run():
    seed()
    c = TestClient(api.app)

    # health needs no key
    r = c.get("/health")
    assert r.status_code == 200 and r.json()["daily_records"] == 2, r.text
    print("ok health")

    # auth enforced
    assert c.get("/farms").status_code == 401
    print("ok auth-required")

    r = c.get("/farms", headers=KEY)
    assert r.status_code == 200 and r.json()[0]["name"] == "כפר הריף", r.text
    print("ok farms")

    r = c.get("/farms/482/flocks", headers=KEY)
    assert r.json()[0]["midgar_text"] == "4-2026" and r.json()[0]["rows"] == 2, r.text
    print("ok flocks")

    r = c.get("/daily", headers=KEY, params={"farm": 482, "flock": "4-2026"})
    d = r.json()
    assert len(d) == 2 and d[0]["record_date"] == "2026-08-25", r.text
    print("ok daily")

    r = c.get("/daily", headers=KEY, params={"farm": 482, "from": "2026-08-25"})
    assert len(r.json()) == 1, r.text
    print("ok daily-filter")

    r = c.get("/summary", headers=KEY, params={"farm": 482, "flock": "4-2026"})
    s = r.json()
    assert s["total_mortality"] == 112 and s["avg_weight"] == 1850.0, r.text
    print("ok summary")

    print("\nALL API TESTS PASSED")


if __name__ == "__main__":
    try:
        run()
    finally:
        if os.path.exists(_path):
            os.remove(_path)
