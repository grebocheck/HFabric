@echo off
REM ===========================================================================
REM  HFabric launcher  (double-click me)
REM
REM    run.bat          -> Auto mode: hardware probe selects REAL/STUB
REM    run.bat stub     -> STUB mode: full pipeline, no GPU/ML stack
REM    run.bat --prod   -> production: one FastAPI port serves frontend/dist
REM
REM  Runs the backend (:8260) and the Vite frontend (:5173) together in THIS
REM  single window, frees any stale ports first, and opens the UI in your
REM  browser. Ctrl+C stops both. First run bootstraps the venv + npm deps.
REM ===========================================================================
setlocal
set "STUBFLAG="
set "PRODFLAG="

:parse
if "%~1"=="" goto parsed
if /I "%~1"=="stub" set "STUBFLAG=-Stub"
if /I "%~1"=="--stub" set "STUBFLAG=-Stub"
if /I "%~1"=="--prod" set "PRODFLAG=-Prod"
shift
goto parse
:parsed

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run.ps1" %STUBFLAG% %PRODFLAG%

echo.
echo [exit] servers stopped.
pause
endlocal
