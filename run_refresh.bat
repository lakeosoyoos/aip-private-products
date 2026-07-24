@echo off
REM Double-click launcher (Windows). Creates the venv on first run, then refreshes + exports.
cd /d "%~dp0"
if not exist ".venv" (
  python -m venv .venv
  ".venv\Scripts\pip" install -q -r requirements.txt
)
".venv\Scripts\python" -m src.refresh --source all --export
echo.
echo Done. Spreadsheet is in .\output\
pause
