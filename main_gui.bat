@echo off
rem ===========================================================================
rem  pdf2word launcher for Windows.  Run it from Explorer (double-click),
rem  CMD (main_gui.bat) or PowerShell (.\main_gui.bat).
rem
rem    main_gui.bat                  GUI, no console window
rem    main_gui.bat paper.pdf ...    command line (same options as `pdf2word`)
rem
rem  Virtual environment - the first match wins ("this folder" is the folder
rem  that contains this file):
rem    1. the folder named by the environment variable PDF2WORD_VENV
rem    2. <this folder>\.venv
rem    3. <this folder>\venv
rem    4. D:\Venvs_collec\Common_venv\pdf2word_venv   (when D:\Venvs_collec\Common_venv exists)
rem    5. <this folder>\.venv                         (otherwise)
rem  A missing environment is created (uv when available, else python -m venv)
rem  and missing packages are installed with `pip install -e .`.  A stamp
rem  (project path + requirements.txt) is kept inside the environment; when
rem  requirements.txt changes or the project folder moves, the packages are
rem  updated on the next start.
rem
rem  Keep this file ASCII only: cmd.exe reads it with the console code page.
rem ===========================================================================
setlocal EnableExtensions
set "HERE=%~dp0"
set "PROJ=%HERE:~0,-1%"
set "SHARED_PARENT=D:\Venvs_collec\Common_venv"
set "SHARED_VENV=%SHARED_PARENT%\pdf2word_venv"

rem ---- 1. choose the virtual environment ------------------------------------
set "VENV="
if defined PDF2WORD_VENV set "VENV=%PDF2WORD_VENV%"
if not defined VENV if exist "%HERE%.venv\" set "VENV=%HERE%.venv"
if not defined VENV if exist "%HERE%venv\" set "VENV=%HERE%venv"
if not defined VENV if exist "%SHARED_PARENT%\" set "VENV=%SHARED_VENV%"
if not defined VENV set "VENV=%HERE%.venv"
set "PY=%VENV%\Scripts\python.exe"
set "PYW=%VENV%\Scripts\pythonw.exe"

set "UV="
uv --version >nul 2>&1
if not errorlevel 1 set "UV=1"

if exist "%PY%" goto :check

rem ---- 2. create the environment --------------------------------------------
echo [pdf2word] Creating virtual environment: %VENV%
if defined UV goto :create_uv
set "BASEPY="
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if not errorlevel 1 set "BASEPY=py -3"
if defined BASEPY goto :create_py
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if not errorlevel 1 set "BASEPY=python"
if not defined BASEPY goto :no_python
:create_py
if not exist "%VENV%\" mkdir "%VENV%" 2>nul
%BASEPY% -m venv "%VENV%"
if errorlevel 1 goto :fail_venv
goto :created
:create_uv
if not exist "%VENV%\" mkdir "%VENV%" 2>nul
uv venv --python ">=3.10" "%VENV%"
if errorlevel 1 goto :fail_venv
:created
if not exist "%PY%" goto :fail_venv

rem ---- 3. check the required packages ----------------------------------------
:check
set "REQ=%PROJ%\requirements.txt"
set "STAMP=%VENV%\pdf2word-install-stamp.txt"
set "WANT=%TEMP%\pdf2word-stamp-%RANDOM%.txt"
set "MISSFILE=%TEMP%\pdf2word-missing-%RANDOM%.txt"
> "%WANT%" echo %PROJ%
>> "%WANT%" type "%REQ%"
set "CHECK=import importlib.metadata as m, re, sys; L = [l.strip() for l in open(sys.argv[1], encoding='utf-8')]; N = [re.match(r'[A-Za-z0-9][A-Za-z0-9._-]*', l).group(0) for l in L if re.match(r'[A-Za-z0-9]', l)] + ['pdf2word']; k = lambda s: re.sub(r'[-_.]+', '-', s).lower(); H = {k(d.metadata['Name'] or '') for d in m.distributions()}; M = [n for n in N if k(n) not in H]; print(*M); sys.exit(1 if M else 0)"
"%PY%" -I -c "%CHECK%" "%REQ%" > "%MISSFILE%" 2>nul
if errorlevel 1 goto :install_missing
if not exist "%STAMP%" goto :first_stamp
fc /b "%STAMP%" "%WANT%" >nul 2>&1
if errorlevel 1 goto :install_update
goto :ready
:first_stamp
copy /y "%WANT%" "%STAMP%" >nul
goto :ready

rem ---- 4. install / update ---------------------------------------------------
:install_missing
set "SOFT="
set "MISSING="
set /p MISSING=<"%MISSFILE%"
if not defined MISSING set "MISSING=(package check failed)"
echo [pdf2word] Missing packages: %MISSING%
goto :install
:install_update
set "SOFT=1"
echo [pdf2word] requirements.txt changed or the folder moved since the last install - updating.
:install
echo [pdf2word] Installing packages into %VENV%
echo [pdf2word] (internet connection needed; the first time takes a few minutes)
if defined UV goto :install_uv
"%PY%" -m pip --version >nul 2>&1
if errorlevel 1 "%PY%" -m ensurepip --upgrade >nul 2>&1
"%PY%" -m pip install -e "%PROJ%"
goto :installed
:install_uv
uv pip install --python "%PY%" -e "%PROJ%"
:installed
if errorlevel 1 goto :install_failed
copy /y "%WANT%" "%STAMP%" >nul
echo [pdf2word] Packages are ready.
goto :ready
:install_failed
if not defined SOFT goto :fatal_install
echo [pdf2word] WARNING: the update failed. Starting with the packages already installed.
goto :ready
:fatal_install
echo [pdf2word] ERROR: package installation failed.
goto :fail

rem ---- 5. run ----------------------------------------------------------------
:ready
if defined WANT del "%WANT%" 2>nul
if defined MISSFILE del "%MISSFILE%" 2>nul
if "%~1"=="" goto :gui
"%PY%" "%HERE%main_gui.py" %*
set "RC=%ERRORLEVEL%"
endlocal & exit /b %RC%

:gui
if not exist "%PYW%" set "PYW=%PY%"
start "" "%PYW%" "%HERE%main_gui.py"
endlocal & exit /b 0

rem ---- errors ----------------------------------------------------------------
:no_python
echo [pdf2word] ERROR: no Python 3.10+ (py or python) and no uv found on PATH.
goto :fail
:fail_venv
echo [pdf2word] ERROR: could not create the virtual environment at %VENV%
goto :fail
:fail
if defined WANT del "%WANT%" 2>nul
if defined MISSFILE del "%MISSFILE%" 2>nul
echo.
echo   To fix: install Python 3.10 or newer from https://www.python.org/downloads/
echo   (tick "Add python.exe to PATH") or install uv from https://docs.astral.sh/uv/,
echo   make sure this PC is online, then run this file again.
echo   To use another environment folder, set PDF2WORD_VENV=^<folder^> first.
if "%~1"=="" pause
endlocal & exit /b 1
