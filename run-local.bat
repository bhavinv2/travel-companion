@echo off
REM ============================================================
REM  Connecting Desis - run locally (SQLite database)
REM  Double-click this file, or run it from any terminal.
REM  Stop the server with Ctrl+C.
REM ============================================================
cd /d "%~dp0"
set FLASK_APP=run.py
set PYTHONIOENCODING=utf-8
REM Database comes from .env (local PostgreSQL: connectingdesis @ 127.0.0.1:5432)

echo Starting Connecting Desis on http://localhost:8080 ...
venv\Scripts\python.exe -m flask run --host 127.0.0.1 --port 8080
pause
