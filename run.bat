@echo off
setlocal
cd /d "%~dp0"
title Soundpad

rem ---- 1. find Python 3.10 or newer
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY goto nopython
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if errorlevel 1 goto nopython

rem ---- 2. private environment in .\.venv (created once, nothing is installed system-wide)
if not exist ".venv\Scripts\python.exe" (
    echo Creating the local Python environment in .venv ...
    %PY% -m venv .venv
    if errorlevel 1 goto failed
)
set "VPY=.venv\Scripts\python.exe"

rem ---- 3. install the libraries only if one of them is missing (no download on a normal launch)
"%VPY%" -c "import numpy, sounddevice, soundfile, soxr, av, pynput" >nul 2>nul
if errorlevel 1 (
    echo Some libraries are missing. Installing them from requirements.txt ^(first start only^) ...
    "%VPY%" -m pip install --disable-pip-version-check -r requirements.txt
    if errorlevel 1 goto failed
)

rem ---- 4. run
"%VPY%" main.py %*
if errorlevel 1 pause
exit /b %errorlevel%

:nopython
echo Python 3.10 or newer was not found.
echo Install it from https://www.python.org/downloads/ ^(tick "Add python.exe to PATH"^) and run this file again.
pause
exit /b 1

:failed
echo.
echo Setup failed. Check your internet connection and run this file again.
pause
exit /b 1
