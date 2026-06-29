@echo off
REM Manager 360 - Jira agile-delivery ingestion runner for Windows Task Scheduler.
REM
REM Use this file as the scheduled task's action. It changes to the repo root,
REM activates the virtualenv if present, and runs the all-teams sync. Any
REM arguments are forwarded to the command, e.g.:
REM   run_sync.bat                 incremental sync of all active teams
REM   run_sync.bat --backfill      historical backfill from each team's start date
REM   run_sync.bat --team RPD      limit to one team
REM
REM The sync command's exit code is propagated so the scheduler can react:
REM   0 = clean, 2 = completed with some failures, 1 = the run crashed.

setlocal
cd /d "%~dp0.."

if exist ".venv\Scripts\activate.bat" call ".venv\Scripts\activate.bat"

python manage.py sync %*
set EXITCODE=%ERRORLEVEL%

endlocal & exit /b %EXITCODE%
