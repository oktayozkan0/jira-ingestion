# Manager 360 — Jira Agile Delivery Ingestion

Scheduled Python routine that pulls Jira data needed for Delivery 360 sprint
metrics and writes it **directly into the Manager 360 Azure SQL database**.

This is a standalone repository, separate from the main Manager 360
application. It is designed to run from the dedicated Windows scheduled-task
machine, 2–4 times per day.

> Task: `manager-360-agile-ingestion` — *Introduce Jira API ingestion routine
> for agile delivery metrics.*

## Boundaries

- **No API in the loop.** The routine talks to Jira and to the database only.
  It does not call the Manager 360 HTTP API.
- **It does not own the schema.** Tables are created and migrated by the main
  Manager 360 app (SQLAlchemy + Alembic). Here we use Tortoise ORM purely to
  *map* the existing tables — schema generation is never invoked.
- **Raw ingestion only.** This routine populates raw Jira fact tables plus the
  sync bookkeeping tables (`jira_sync_runs`, `jira_sync_state`). Computing the
  refined Delivery 360 metric tables is a separate task.

In scope for ingestion: dimensions (issue types, statuses, priorities, users),
boards, sprints, issues (incl. story points and changelog), and sprint-issue
membership.

## Requirements

- Python 3.13
- Microsoft **ODBC Driver 18 for SQL Server** installed on the host
- Network access to the Azure SQL database and to Jira Cloud

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt

copy .env.example .env          # then fill in the values
```

Credentials (Jira API token, database password) are supplied through the
environment / `.env` and are never committed.

## Verify connectivity

Before scheduling anything, confirm the database is reachable:

```bash
python manage.py check-db
```

## Commands

| Command | Purpose |
| ------- | ------- |
| `python manage.py check-db` | Verify database connectivity. |
| `python manage.py sync` | Incremental sync of all active configured teams. |
| `python manage.py sync --backfill` | Historical backfill from each team's start date. |
| `python manage.py sync --team RPD` | Limit a run to specific team key(s); repeatable. |
| `python manage.py sync-dimensions` | Ingest only the global reference dimensions. |
| `python manage.py sync-issues --team RPD [--backfill]` | Ingest issues for one team. |

## Scheduling

The recurring run executes from the dedicated Windows scheduled-task machine via
[`scripts/run_sync.bat`](scripts/run_sync.bat). See
[docs/scheduling.md](docs/scheduling.md) for setup, the initial backfill, the
`schtasks` schedule (2–4×/day), and the exit-code contract.

## How it works

Each run fetches the searching account's timezone once, ingests the global
dimensions (issue types, statuses, priorities), then for every active team
ingests boards → sprints → issues in order. Issues bring their story points,
embedded dimensions/users, parent/epic links, changelog
(`jira_issue_field_changes`) and sprint membership (`jira_sprint_issues`).

Incremental runs resume from a per-team / per-entity watermark
(`jira_sync_state`); the watermark only advances after a clean pass, so failures
are retried from the same point. Pagination, Jira rate limits (HTTP 429/503 with
`Retry-After`) and transient network errors are handled by the vendored client.
Every team/entity run records a `jira_sync_runs` audit row (status, duration,
record counts), and one team's failure is isolated from the rest.
