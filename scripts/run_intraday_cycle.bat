@echo off
REM StockSight — headless intraday cycle (gap + intraday scan + CSV export)
REM Run from repo root:  scripts\run_intraday_cycle.bat
REM Or double-click after cloning the repo.

setlocal
cd /d "%~dp0\.."

if not exist "stocksight\intraday.py" (
  echo ERROR: Run from stocksight2 repo root. Missing stocksight\intraday.py
  exit /b 1
)

where python >nul 2>&1
if errorlevel 1 (
  echo ERROR: Python not found on PATH. Install Python 3.11+ and retry.
  exit /b 1
)

echo [%date% %time%] Starting intraday cycle...
python scripts\intraday_cycle.py %*
set EXITCODE=%ERRORLEVEL%

if %EXITCODE% neq 0 (
  echo Cycle failed with exit code %EXITCODE%
  exit /b %EXITCODE%
)

echo Cycle finished. Outputs in output\intraday\
endlocal
exit /b 0
