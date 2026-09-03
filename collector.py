"""
Local collector for the Poultrix Kfar Harif watcher.

Listens on http://127.0.0.1:8765 and accepts:
  POST /save   body: {"timestamp": "...", "changes": [...], "grids": [...]}

Writes to files in the DATA_DIR folder (next to this script):
  kfar_harif_changes.jsonl  -> one JSON line per run that had changes (append-only history)
  kfar_harif_latest.json    -> the full latest scrape (overwritten each run)
  kfar_harif_log.txt        -> human-readable running log

The Tampermonkey userscript posts here with GM_xmlhttpRequest.

Run:  pythonw collector.py   (via the startup shortcut / scheduled task)
"""
import json
import os
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import db  # SQLite warehouse

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = HERE
HOST, PORT = "127.0.0.1", 8765

CHANGES = os.path.join(DATA_DIR, "kfar_harif_changes.jsonl")
LATEST = os.path.join(DATA_DIR, "kfar_harif_latest.json")
LOGTXT = os.path.join(DATA_DIR, "kfar_harif_log.txt")


# fields to render in the human-readable log, in order
LOG_FIELDS = [
    ("date", "תאריך"), ("building", "מבנה"), ("age", "גיל"),
    ("mortality", "תמותה"), ("culls", "פסילה"), ("weight", "משקל"),
    ("feed", "מזון"), ("water", "מים"), ("population", "ס.אכלוס"),
    ("totalMort", "סהכ תמותה"), ("cumMort", "תמותה מצט"),
    ("stdWeight", "משקל תקן"), ("notes", "הערות"),
]


def save(payload):
    ts = payload.get("timestamp") or datetime.now().isoformat(timespec="seconds")
    changes = payload.get("changes", [])
    rows = payload.get("rows", [])
    farm = payload.get("farm", "")
    farm_id = payload.get("farmId") or payload.get("farm_id")
    midgar = payload.get("flock") or payload.get("midgar") or ""
    mode = payload.get("mode", "incremental")

    # --- warehouse: upsert into SQLite (the central store) ---
    db_result = {}
    try:
        con = db.connect()
        db.save_raw(con, farm_id, farm, midgar, {"timestamp": ts, "rows": rows})
        ins, upd, skip = db.upsert_rows(con, farm_id, farm, midgar, rows, mode=mode)
        con.close()
        db_result = {"inserted": ins, "updated": upd, "skipped": skip}
    except Exception as e:
        db_result = {"db_error": str(e)}

    # full latest snapshot (overwrite) - all current rows
    with open(LATEST, "w", encoding="utf-8") as f:
        json.dump({"timestamp": ts, "farm": farm, "rowCount": len(rows), "rows": rows},
                  f, ensure_ascii=False, indent=2)

    # append-only history of changes
    if changes:
        with open(CHANGES, "a", encoding="utf-8") as f:
            f.write(json.dumps({"timestamp": ts, "farm": farm, "changes": changes},
                               ensure_ascii=False) + "\n")

    # human-readable log
    with open(LOGTXT, "a", encoding="utf-8") as f:
        f.write(f"\n===== {ts} {farm} =====\n")
        if not changes:
            f.write("no changes\n")
        for c in changes:
            parts = [f"{heb}={c.get(k)}" for k, heb in LOG_FIELDS
                     if c.get(k) not in (None, "", "0")]
            f.write(f"[{c.get('type', '')}] " + ", ".join(parts) + "\n")

    return {"ok": True, "saved_changes": len(changes), "rows": len(rows), "db": db_result}


class Handler(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")

    def do_OPTIONS(self):
        self.send_response(204); self._cors(); self.end_headers()

    def do_GET(self):
        self.send_response(200); self._cors()
        self.send_header("Content-Type", "text/plain; charset=utf-8"); self.end_headers()
        self.wfile.write(b"poultrix-collector ok")

    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(n).decode("utf-8"))
            res = save(payload)
            out, code = json.dumps(res).encode("utf-8"), 200
        except Exception as e:
            out, code = json.dumps({"ok": False, "error": str(e)}).encode("utf-8"), 500
        self.send_response(code); self._cors()
        self.send_header("Content-Type", "application/json"); self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print(f"Poultrix collector listening on http://{HOST}:{PORT}  ->  {DATA_DIR}")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
