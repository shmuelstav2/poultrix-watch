# poultrix-watch

Hourly watcher for חוות כפר הריף (Poultrix farm id 482): scrapes the daily grid
(mortality / weighings / feed per building×date) and saves changes to files on
the server. No email, no API — runs inside the logged-in browser session.

## Components
- `poultrix_watch.user.js` — Tampermonkey userscript on `DailyFollowUpV1.aspx`:
  hourly scrape + diff, POSTs changes to the local collector. 5-min keep-alive
  prevents ASP.NET session timeout.
- `collector.py` — local server 127.0.0.1:8765; writes `kfar_harif_latest.json`,
  `kfar_harif_changes.jsonl`, `kfar_harif_log.txt`.
- `check_deploy.ps1` — runs every minute (scheduled task): `git pull`; on a new
  commit redeploys + restarts the collector; also watchdogs the collector.
- `bootstrap.ps1` — one-time: clone repo, register the deploy task, start collector.

## DevOps flow
Edit locally → `git push`. Within ~1 minute the server's PoultrixDeploy task
pulls the new commit, restarts the collector, and writes `deploy_status.txt`.
