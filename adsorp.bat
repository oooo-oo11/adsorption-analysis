@echo off
rem One-click entry: adsorp run / template / check
setlocal
cd /d "%~dp0"
set PY="C:\Users\Uers\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
if not exist %PY% set PY=python
%PY% -m adsorp.cli %*
