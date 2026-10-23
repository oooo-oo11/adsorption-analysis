@echo off
rem =====================================================================
rem  Adsorption analysis - one-click entry (cmd / PowerShell / double-click)
rem
rem  Double-click    : find data, run full analysis, open report at the end
rem  adsorp.bat run  : same, but do not open the report
rem  adsorp.bat template / check / export / matlab : see README
rem
rem  Python lookup: ADSORP_PYTHON -> python\ (bundled) -> .venv -> py -3 -> python
rem  Only interpreters that can import the required packages are used.
rem  This package ships a portable Python in python\ , so a fresh machine
rem  needs nothing installed.
rem =====================================================================
setlocal EnableExtensions
cd /d "%~dp0"
title Adsorption analysis

rem Show Chinese output correctly; ignore failure on old systems.
chcp 65001 >nul 2>nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

set "PY_CMD="

if defined ADSORP_PYTHON call :try_exe "%ADSORP_PYTHON%"
if not defined PY_CMD if exist "python\python.exe" call :try_exe "python\python.exe"
if not defined PY_CMD if exist ".venv\Scripts\python.exe" call :try_exe ".venv\Scripts\python.exe"
if not defined PY_CMD call :try_launcher py -3
if not defined PY_CMD call :try_launcher python

if not defined PY_CMD goto :nopython

%PY_CMD% -m adsorp.cli %*
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" goto :failed

rem Double-click (no arguments): open the report when the run succeeded.
if "%~1"=="" if exist "output\*.html" for %%F in ("output\*.html") do start "" "%%~fF"
goto :done

:failed
echo.
echo [FAILED] exit code %RC% - see the messages above.

:done
rem Keep the window open when launched by double-click.
if "%~1"=="" pause
exit /b %RC%

:nopython
echo [ERROR] No usable Python found.
echo         Requires: numpy pandas scipy matplotlib openpyxl
echo.
echo   This package normally ships its own Python in python\ .
echo   If that folder is missing, either restore it or:
echo     Option 1: install Python 3.10+ with "Add python.exe to PATH" checked
echo     Option 2: python -m venv .venv
echo               .venv\Scripts\python -m pip install -r requirements.txt
echo     Option 3: set ADSORP_PYTHON to the full path of python.exe
echo.
if "%~1"=="" pause
exit /b 1

rem ---------------------------------------------------------------------
:try_exe
if not exist "%~1" goto :eof
"%~1" -c "import numpy, pandas, scipy, matplotlib, openpyxl" >nul 2>nul
if not errorlevel 1 set "PY_CMD="%~1""
goto :eof

:try_launcher
if "%~2"=="" (
  %~1 -c "import numpy, pandas, scipy, matplotlib, openpyxl" >nul 2>nul
) else (
  %~1 %~2 -c "import numpy, pandas, scipy, matplotlib, openpyxl" >nul 2>nul
)
if not errorlevel 1 set "PY_CMD=%~1 %~2"
goto :eof
