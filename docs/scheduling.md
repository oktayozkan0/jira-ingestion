# Running on the Windows scheduled-task machine

The ingestion routine runs from the dedicated Windows scheduled-task machine,
2–4 times per day. It pulls Jira data for every active configured team and
writes straight into the Manager 360 Azure SQL database.

## One-time setup

1. Install **Python 3.13** and the **ODBC Driver 18 for SQL Server**.
2. Clone the repo and create the environment:
   ```bat
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```
3. Create `.env` from `.env.example` and fill in the database connection and
   Jira credentials. `.env` is never committed.
4. Verify connectivity before scheduling anything:
   ```bat
   python manage.py check-db
   ```

## Initial backfill

Run a one-off historical backfill so each team has data from its configured
`tracking_start_date` (or `DEFAULT_BACKFILL_START_DATE`):

```bat
scripts\run_sync.bat --backfill
```

Backfill is resumable: the watermark only advances after a clean pass, so a
failed or interrupted run is retried from where it left off on the next run.

## Schedule the recurring sync

The task action is [`scripts\run_sync.bat`](../scripts/run_sync.bat); it activates
the virtualenv, runs `python manage.py sync`, and propagates the exit code.

Create the task (example: every 6 hours = 4×/day) with `schtasks`, or via the
Task Scheduler UI:

```bat
schtasks /Create ^
  /TN "Manager360 Jira Ingestion" ^
  /TR "C:\path\to\manager-360-agile-ingestion\scripts\run_sync.bat" ^
  /SC HOURLY /MO 6 ^
  /RU "DOMAIN\service-account" /RP * ^
  /RL LIMITED /F
```

- `/MO 6` → every 6 hours (4×/day). Use `/MO 8` for 3×/day or `/MO 12` for 2×.
- In the UI: "Run whether user is logged on or not", and set **Start in** to the
  repo root so relative paths resolve.

## Exit codes

The scheduled task surfaces the sync's exit code (Last Run Result):

| Code | Meaning |
| ---- | ------- |
| `0`  | Clean run — all teams ingested. |
| `2`  | Completed, but one or more team/entity scopes failed (see logs). |
| `1`  | The run could not start or crashed before finishing. |

Alert on non-zero results. Each run also writes a `jira_sync_runs` audit row per
team/entity (status, duration, and record counts) and a per-run summary log line.

## Logs

Set `LOG_DIR` in `.env` to capture rotating run logs (`ingestion.log`); leave it
empty to log to the console only.

## Commands

| Command | Purpose |
| ------- | ------- |
| `python manage.py check-db` | Verify database connectivity. |
| `python manage.py sync` | Incremental sync of all active teams (the scheduled command). |
| `python manage.py sync --backfill` | Historical backfill of all active teams. |
| `python manage.py sync --team RPD` | Limit a run to specific team key(s); repeatable. |
| `python manage.py sync-dimensions` | Ingest only the global reference dimensions. |
| `python manage.py sync-issues --team RPD [--backfill]` | Ingest issues for a single team. |
