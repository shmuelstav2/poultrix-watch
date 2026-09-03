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

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = HERE
HOST, PORT = "127.0.0.1", 8765

CHANGES = os.path.join(DATA_DIR, "kfar_harif_changes.jsonl")
LATEST = os.path.join(DATA_DIR, "kfar_harif_latest.json")
LOGTXT = os.path.join(DATA_DIR, "kfar_harif_log.txt")


def save(payload):
    ts = payload.get("timestamp") or datetime.now().isoformat(timespec="seconds")
    changes = payload.get("changes", [])
    grids = payload.get("grids", [])

    # full latest snapshot (overwrite)
    with open(LATEST, "w", encoding="utf-8") as f:
        json.dump({"timestamp": ts, "grids": grids}, f, ensure_ascii=False, indent=2)

    # append-only history of changes
    if changes:
        with open(CHANGES, "a", encoding="utf-8") as f:
            f.write(json.dumps({"timestamp": ts, "changes": changes}, ensure_ascii=False) + "\n")

    # human-readable log
    with open(LOGTXT, "a", encoding="utf-8") as f:
        f.write(f"\n===== {ts} =====\n")
        if not changes:
            f.write("no changes\n")
        for c in changes:
            hdr = c.get("headers") or []
            row = c.get("row") or []
            if hdr and len(hdr) == len(row):
                pairs = ", ".join(f"{h}={v}" for h, v in zip(hdr, row) if v)
            else:
                pairs = " | ".join(row)
            f.write(f"[{c.get('grid','')}] {pairs}\n")

    return {"ok": True, "saved_changes": len(changes), "grids": len(grids)}


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
