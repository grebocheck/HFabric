@echo off
REM ===========================================================================
REM  HFabric updater  (double-click me)
REM
REM    update.bat             -> git pull + refresh dependencies
REM    update.bat stub        -> refresh as STUB / CPU-safe
REM    update.bat all         -> refresh + starter models + voice assets
REM    update.bat --no-pull   -> only refresh local dependencies
REM    update.bat --prod      -> also rebuild frontend/dist
REM
REM  Uses the same local Python/Node bootstrap as setup.bat/run.bat.
REM ===========================================================================
setlocal
set "ARGS="

:parse
if "%~1"=="" goto parsed
if /I "%~1"=="stub" set "ARGS=%ARGS% -Stub"
if /I "%~1"=="--stub" set "ARGS=%ARGS% -Stub"
if /I "%~1"=="all" set "ARGS=%ARGS% -DownloadAll"
if /I "%~1"=="--all" set "ARGS=%ARGS% -DownloadAll"
if /I "%~1"=="--no-pull" set "ARGS=%ARGS% -NoPull"
if /I "%~1"=="--prod" set "ARGS=%ARGS% -Prod"
if /I "%~1"=="--force" set "ARGS=%ARGS% -Force"
shift
goto parse
:parsed

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0update.ps1" %ARGS%

echo.
echo [update] complete.
pause
endlocal
