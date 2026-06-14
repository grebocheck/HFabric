@echo off
REM ===========================================================================
REM  HFabric Automated Setup  (double-click me)
REM
REM    setup.bat             -> Auto setup (hardware probe -> recommended profile)
REM    setup.bat stub        -> STUB mode setup (no GPU)
REM    setup.bat real        -> Force accelerator setup when available
REM    setup.bat all         -> Accelerator setup + profile starter models
REM
REM  Sets up everything: venv, dependencies (foundation + accelerator), npm, and
REM  optionally downloads model files. After setup completes, run.bat starts
REM  the app.
REM ===========================================================================
setlocal
set "SETUPFLAG="
if /I "%~1"=="stub" set "SETUPFLAG=-Stub"
if /I "%~1"=="real" set "SETUPFLAG=-Real"
if /I "%~1"=="all" set "SETUPFLAG=-DownloadAll"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %SETUPFLAG%

echo.
echo [setup] complete. Ready to run: run.bat
echo.
pause
endlocal
