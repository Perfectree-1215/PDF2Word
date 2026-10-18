@echo off
rem ===========================================================================
rem  pdf2word launcher for Windows.  Run it from Explorer (double-click),
rem  CMD (main_gui.bat) or PowerShell (.\main_gui.bat).
rem
rem    main_gui.bat                  GUI, no console window
rem    main_gui.bat paper.pdf ...    command line (same options as `pdf2word`)
rem
rem  Python: 3.10, 3.11 or 3.12 only.  The equation OCR package rapid_latex_ocr
rem  requires numpy < 2, and numpy 1.x has no wheels for Python 3.13 or newer,
rem  so the packages cannot be installed into a newer interpreter.  The range
rem  is set once below (PY_MIN / PY_MAX / PY_TOP) - keep it in sync with
rem  requires-python in pyproject.toml and .python-version.
rem
rem  Virtual environment - the first match wins ("this folder" is the folder
rem  that contains this file):
rem    1. the folder named by the environment variable PDF2WORD_VENV
rem    2. <this folder>\.venv
rem    3. <this folder>\venv
rem    4. D:\Venvs_collec\Common_venv\pdf2word_venv   (when D:\Venvs_collec\Common_venv exists)
rem    5. <this folder>\.venv                         (otherwise)
rem  A missing environment is created with a supported Python: uv (when
rem  available) picks an installed interpreter inside the range or downloads
rem  one; without uv the py launcher is asked for 3.12, 3.11, 3.10 in turn,
rem  then "py -3" / "python" are accepted if their version is inside the range.
rem  An existing environment whose Python is outside the range is refused with
rem  an explanation instead of failing half-way through the package install.
rem  Missing packages are installed with `pip install -e .`.  A stamp (project
rem  path + requirements.txt) is kept inside the environment; when
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

rem ---- supported Python range: PY_MIN <= version < PY_MAX (PY_TOP = highest) --
set "PY_MIN=3.10"
set "PY_MAX=3.13"
set "PY_TOP=3.12"
set "PY_CANDIDATES=3.12 3.11 3.10"
set "PY_RANGE=>=%PY_MIN%,<%PY_MAX%"
set "PY_CHECK=import sys; lo = tuple(int(x) for x in '%PY_MIN%'.split('.')); hi = tuple(int(x) for x in '%PY_MAX%'.split('.')); sys.exit(0 if lo <= sys.version_info[:2] < hi else 1)"

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

if exist "%PY%" goto :verify

rem ---- 2. create the environment with a supported Python --------------------
echo [pdf2word] Creating virtual environment: %VENV%
echo [pdf2word] (Python %PY_MIN% - %PY_TOP% is required; %PY_MAX% or newer cannot install the packages)
if defined UV goto :create_uv
call :find_python
if not defined BASEPY goto :no_python
if not exist "%VENV%\" mkdir "%VENV%" 2>nul
echo [pdf2word] Using "%BASEPY%"
%BASEPY% -m venv "%VENV%"
if errorlevel 1 goto :fail_venv
goto :created
:create_uv
if not exist "%VENV%\" mkdir "%VENV%" 2>nul
rem uv takes an installed interpreter inside the range or downloads one (internet needed)
uv venv --python "%PY_RANGE%" "%VENV%"
if errorlevel 1 goto :fail_venv
:created
if not exist "%PY%" goto :fail_venv

rem ---- 3. refuse an environment whose Python is outside the range -----------
:verify
"%PY%" -I -c "%PY_CHECK%" >nul 2>&1
if errorlevel 1 goto :bad_venv

rem ---- 4. check the required packages ----------------------------------------
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

rem ---- 5. install / update ---------------------------------------------------
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

rem ---- 6. run ----------------------------------------------------------------
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

rem ---- subroutine: find a base interpreter inside the range (no uv) ----------
:find_python
set "BASEPY="
for %%V in (%PY_CANDIDATES%) do (
    if not defined BASEPY (
        py -%%V -I -c "%PY_CHECK%" >nul 2>&1
        if not errorlevel 1 set "BASEPY=py -%%V"
    )
)
if defined BASEPY goto :eof
py -3 -I -c "%PY_CHECK%" >nul 2>&1
if not errorlevel 1 set "BASEPY=py -3"
if defined BASEPY goto :eof
python -I -c "%PY_CHECK%" >nul 2>&1
if not errorlevel 1 set "BASEPY=python"
goto :eof

rem ---- errors ----------------------------------------------------------------
:no_python
echo [pdf2word] ERROR: no Python %PY_MIN% - %PY_TOP% found (py launcher or python on PATH) and no uv.
echo.
echo   To fix: install Python %PY_TOP% from https://www.python.org/downloads/ and tick
echo   "Add python.exe to PATH" (%PY_MIN% - %PY_TOP% work, %PY_MAX% or newer does not), or install
echo   uv from https://docs.astral.sh/uv/ - uv downloads a suitable Python by itself.
echo   Then make sure this PC is online and run this file again.
goto :fail
:fail_venv
echo [pdf2word] ERROR: could not create the virtual environment at %VENV%
echo.
echo   To fix: make sure this PC is online (uv may need to download Python), check that
echo   the folder can be written, or set PDF2WORD_VENV=^<folder^> to use another location.
goto :fail
:bad_venv
set "VENV_PYVER=a Python that does not start (broken environment)"
set "VENV_PYNUM="
"%PY%" -I -c "import sys; print(sys.version.split()[0])" > "%TEMP%\pdf2word-pyver.txt" 2>nul
if not errorlevel 1 set /p VENV_PYNUM=<"%TEMP%\pdf2word-pyver.txt"
if defined VENV_PYNUM set "VENV_PYVER=Python %VENV_PYNUM%"
del "%TEMP%\pdf2word-pyver.txt" 2>nul
echo [pdf2word] ERROR: the environment %VENV%
echo [pdf2word]        uses %VENV_PYVER%, but pdf2word needs Python %PY_MIN% - %PY_TOP%.
echo.
echo   To fix: delete that folder (or set PDF2WORD_VENV=^<folder^> to use another one) and
echo   run this file again - a new environment with a supported Python is created.
goto :fail
:fatal_install
echo [pdf2word] ERROR: package installation failed.
echo.
echo   To fix: make sure this PC is online and run this file again.  If it keeps
echo   failing, delete %VENV% so that a fresh environment is created.
goto :fail
:fail
if defined WANT del "%WANT%" 2>nul
if defined MISSFILE del "%MISSFILE%" 2>nul
if "%~1"=="" pause
endlocal & exit /b 1
