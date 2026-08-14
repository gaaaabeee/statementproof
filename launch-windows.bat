@echo off
REM Double-click this to start statementproof.
REM It runs entirely on your machine; the only socket is a loopback server.
cd /d "%~dp0"

set PY=
if exist ".venv\Scripts\python.exe" set PY=.venv\Scripts\python.exe
if "%PY%"=="" (
  py -3 -c "import sys" >nul 2>&1 && set PY=py -3
)
if "%PY%"=="" (
  python -c "import sys" >nul 2>&1 && set PY=python
)
if "%PY%"=="" (
  echo Python 3.9+ is required. Install it from https://python.org and try again.
  pause
  exit /b 1
)

%PY% -c "import pypdf" >nul 2>&1
if errorlevel 1 (
  echo Installing the one dependency ^(pypdf^)...
  %PY% -m pip install --quiet -r requirements.txt
)

%PY% -u -m statementproof.app
pause
