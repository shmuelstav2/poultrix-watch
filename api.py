"""
Poultrix warehouse API (FastAPI, read-only, API-key auth).

Run:  POULTRIX_API_KEY=<key> uvicorn api:app --host 0.0.0.0 --port 8000

Endpoints (all except /health require header  X-API-Key: <key>):
  GET /health
  GET /farms
  GET /farms/{poultrix_id}/flocks
  GET /daily?farm=&flock=&from=&to=&building=&limit=&offset=
  GET /summary?farm=&flock=
"""
import os

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query

import db

_KEY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "api_key.txt")


def _load_key():
    k = os.environ.get("POULTRIX_API_KEY")
    if k:
        return k
    if os.path.exists(_KEY_FILE):
        return open(_KEY_FILE, encoding="utf-8").read().strip()
    return "changeme-poultrix-key"


API_KEY = _load_key()

app = FastAPI(title="Poultrix Warehouse API", version="1.0")


def require_key(x_api_key: str = Header(default="")):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="invalid or missing X-API-Key")
    return True


def q(sql, params=()):
    con = db.connect()
    try:
        return [dict(r) for r in con.execute(sql, params).fetchall()]
    finally:
        con.close()


@app.get("/health")
def health():
    con = db.connect()
    try:
        n = con.execute("SELECT COUNT(*) FROM daily_records").fetchone()[0]
        farms = con.execute("SELECT COUNT(*) FROM farms").fetchone()[0]
        return {"ok": True, "daily_records": n, "farms": farms}
    finally:
        con.close()


@app.get("/farms", dependencies=[Depends(require_key)])
def farms():
    return q("SELECT poultrix_id, name, first_seen, last_seen FROM farms ORDER BY name")


@app.get("/farms/{poultrix_id}/flocks", dependencies=[Depends(require_key)])
def flocks(poultrix_id: int):
    return q(
        "SELECT midgar_text, MIN(record_date) start_date, MAX(record_date) end_date, "
        "COUNT(*) rows FROM daily_records WHERE farm_poultrix_id=? "
        "GROUP BY midgar_text ORDER BY end_date DESC", (poultrix_id,))


@app.get("/daily", dependencies=[Depends(require_key)])
def daily(farm: int = Query(None), flock: str = Query(None),
          from_: str = Query(None, alias="from"), to: str = Query(None),
          building: str = Query(None), limit: int = 500, offset: int = 0):
    where, params = [], []
    if farm is not None:
        where.append("farm_poultrix_id=?"); params.append(farm)
    if flock:
        where.append("midgar_text=?"); params.append(flock)
    if from_:
        where.append("record_date>=?"); params.append(from_)
    if to:
        where.append("record_date<=?"); params.append(to)
    if building:
        where.append("building=?"); params.append(building)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    params += [min(limit, 5000), offset]
    return q(f"SELECT farm_poultrix_id, farm_name, midgar_text, building, record_date, "
             f"age_text, gender, mortality, culls, weight, feed, total_mortality, "
             f"cum_mortality, std_weight, notes FROM daily_records {clause} "
             f"ORDER BY record_date DESC, building LIMIT ? OFFSET ?", params)


@app.get("/summary", dependencies=[Depends(require_key)])
def summary(farm: int = Query(...), flock: str = Query(...)):
    rows = q("SELECT COUNT(*) rows, SUM(mortality) total_mortality, "
             "MAX(cum_mortality) cum_mortality, MAX(record_date) last_date, "
             "MIN(record_date) first_date, "
             "AVG(NULLIF(weight,0)) avg_weight FROM daily_records "
             "WHERE farm_poultrix_id=? AND midgar_text=?", (farm, flock))
    return rows[0] if rows else {}


@app.get("/reports", dependencies=[Depends(require_key)])
def reports(farm: int = Query(None), flock: str = Query(None),
            domain: str = Query(None), limit: int = 2000, offset: int = 0):
    where, params = [], []
    if farm is not None:
        where.append("farm_poultrix_id=?"); params.append(farm)
    if flock:
        where.append("midgar_text=?"); params.append(flock)
    if domain:
        where.append("domain=?"); params.append(domain)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    params += [min(limit, 10000), offset]
    import json as _j
    rows = q(f"SELECT farm_poultrix_id, farm_name, midgar_text, domain, row_json "
             f"FROM report_rows {clause} ORDER BY id LIMIT ? OFFSET ?", params)
    for r in rows:
        r["data"] = _j.loads(r.pop("row_json"))
    return rows


@app.get("/reports/summary", dependencies=[Depends(require_key)])
def reports_summary(domain: str = Query(None)):
    clause = "WHERE domain=?" if domain else ""
    p = [domain] if domain else []
    return q(f"SELECT farm_name, midgar_text, domain, COUNT(*) rows FROM report_rows {clause} "
             f"GROUP BY farm_poultrix_id, midgar_text, domain ORDER BY farm_name", p)
