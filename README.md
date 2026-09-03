# poultrix-watch

Hourly watcher for חוות כפר הריף (Poultrix farm id 482).

- `poultrix_watch.user.js` — Tampermonkey userscript: runs on the logged-in
  `DailyFollowUpV1.aspx` page, hourly scrapes the daily grid (mortality /
  weighings / feed per building×date), diffs vs last run, POSTs changes to the
  local collector. 5-min keep-alive prevents ASP.NET session timeout.
- `collector.py` — local server on 127.0.0.1:8765; writes
  `kfar_harif_latest.json`, `kfar_harif_changes.jsonl`, `kfar_harif_log.txt`.
- `deploy.ps1` — `git pull` + restart collector.
- `setup-task.ps1` — register the collector as a startup task (run once).

## Deploy
Edit locally -> commit -> push. On the server: `powershell -ExecutionPolicy Bypass -File deploy.ps1`
