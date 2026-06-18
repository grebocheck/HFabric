@echo off
REM ===========================================================================
REM  HFabric launcher  (double-click me)
REM
REM    run.bat          -> Auto mode: hardware probe selects REAL/STUB
REM    run.bat stub     -> STUB mode: full pipeline, no GPU/ML stack
REM    run.bat --prod   -> production: one FastAPI port serves frontend/dist
REM    run.bat --no-open -> do not open the browser automatically
REM
REM  Runs the backend (:8260) and the Vite frontend (:5173) together in THIS
REM  single window, frees any stale ports first, and opens the UI in your
REM  browser. Ctrl+C stops both. First run bootstraps local Python/Node when
REM  needed, then creates/repairs the venv + npm deps.
REM ===========================================================================
setlocal
set "STUBFLAG="
set "PRODFLAG="
set "OPENFLAG="

:parse
if "%~1"=="" goto parsed
if /I "%~1"=="stub" set "STUBFLAG=-Stub"
if /I "%~1"=="--stub" set "STUBFLAG=-Stub"
if /I "%~1"=="--prod" set "PRODFLAG=-Prod"
if /I "%~1"=="--no-open" set "OPENFLAG=-NoOpen"
shift
goto parse
:parsed

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run.ps1" %STUBFLAG% %PRODFLAG% %OPENFLAG%

echo.
echo [exit] servers stopped.
pause
endlocal
