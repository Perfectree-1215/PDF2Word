@echo off
rem ===========================================================================
rem  pdf2word launcher for Windows.  Run it from Explorer (double-click),
rem  CMD (main_gui.bat) or PowerShell (.\main_gui.bat).
rem
rem    main_gui.bat                  GUI, no console window
rem    main_gui.bat paper.pdf ...    command line (same options as `pdf2word`)
rem
rem  Python: the virtual environment is ALWAYS created with Python 3.12 (PY_TOP),
rem  whatever Python versions this PC has installed.  The equation OCR package
rem  rapid_latex_ocr requires numpy < 2, and numpy 1.x has no wheels for Python
rem  3.13 or newer, so the packages cannot be installed into a newer interpreter.
rem  An existing environment is accepted only when its Python is 3.12 as well
rem  (PY_MIN <= version < PY_MAX, both set to 3.12 / 3.13): an environment made
rem  elsewhere with another version is refused with an explanation.  Keep PY_TOP
rem  in sync with .python-version (3.12); pyproject.toml's requires-python stays
rem  the wider range the package itself can run on.
rem
rem  Virtual environment - the first match wins ("this folder" is the folder
rem  that contains this file):
rem    1. the folder named by the environment variable PDF2WORD_VENV
rem    2. <this folder>\.venv
rem    3. <this folder>\venv
rem    4. D:\Venvs_collec\Common_venv\pdf2word_venv   (when D:\Venvs_collec\Common_venv exists)
rem    5. <this folder>\.venv                         (otherwise)
rem  A missing environment is created with Python 3.12, in this order:
rem    a. uv is installed (on PATH, %USERPROFILE%\.local\bin or WinGet): uv uses an
rem       installed Python 3.12 or downloads one into its own store (no admin rights,
rem       nothing else on the PC changes).
rem    b. no uv, but Python 3.12 is installed (`py -3.12` or `python`): plain venv.
rem    c. neither: uv is installed with the official installer (astral.sh, falls
rem       back to winget), then a. - so a PC with only Python 3.13/3.14 or no Python
rem       at all works too.  Internet connection needed.
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

rem ---- supported Python range: PY_MIN <= version < PY_MAX; PY_TOP = the version
rem ---- new environments are created with -----------------------------------
set "PY_MIN=3.12"
set "PY_MAX=3.13"
set "PY_TOP=3.12"
set "PY_CHECK=import sys; lo = tuple(int(x) for x in '%PY_MIN%'.split('.')); hi = tuple(int(x) for x in '%PY_MAX%'.split('.')); sys.exit(0 if lo <= sys.version_info[:2] < hi else 1)"
set "PY_EXACT=import sys; sys.exit(0 if sys.version_info[:2] == tuple(int(x) for x in '%PY_TOP%'.split('.')) else 1)"
rem let uv download Python %PY_TOP% even when a user-level uv config says "never"
set "UV_PYTHON_DOWNLOADS=automatic"

rem ---- 1. choose the virtual environment ------------------------------------
set "VENV="
if defined PDF2WORD_VENV set "VENV=%PDF2WORD_VENV%"
if not defined VENV if exist "%HERE%.venv\" set "VENV=%HERE%.venv"
if not defined VENV if exist "%HERE%venv\" set "VENV=%HERE%venv"
if not defined VENV if exist "%SHARED_PARENT%\" set "VENV=%SHARED_VENV%"
if not defined VENV set "VENV=%HERE%.venv"
set "PY=%VENV%\Scripts\python.exe"
set "PYW=%VENV%\Scripts\pythonw.exe"

call :locate_uv

if exist "%PY%" goto :verify

rem ---- 2. create the environment with Python %PY_TOP% ------------------------
echo [pdf2word] Creating virtual environment: %VENV%
echo [pdf2word] (always with Python %PY_TOP%, whatever Python this PC has installed)
if defined UV goto :create_uv
call :find_python
if defined BASEPY goto :create_py
echo [pdf2word] Python %PY_TOP% is not installed and uv was not found.
echo [pdf2word] Installing uv, which then downloads Python %PY_TOP% by itself (internet connection needed)...
call :install_uv
if not defined UV goto :no_python
echo [pdf2word] uv installed: %UV%
goto :create_uv
:create_py
if not exist "%VENV%\" mkdir "%VENV%" 2>nul
echo [pdf2word] Using "%BASEPY%"
%BASEPY% -m venv "%VENV%"
if errorlevel 1 goto :fail_venv
goto :created
:create_uv
if not exist "%VENV%\" mkdir "%VENV%" 2>nul
rem uv takes an installed Python %PY_TOP% or downloads one into its own store (internet needed)
echo [pdf2word] Using uv (%UV%) with Python %PY_TOP%
"%UV%" venv --python %PY_TOP% "%VENV%"
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
if defined UV goto :install_pkgs_uv
"%PY%" -m pip --version >nul 2>&1
if errorlevel 1 "%PY%" -m ensurepip --upgrade >nul 2>&1
"%PY%" -m pip install -e "%PROJ%"
goto :installed
:install_pkgs_uv
"%UV%" pip install --python "%PY%" -e "%PROJ%"
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

rem ---- subroutine: find uv (PATH, official installer folder, WinGet) ----------
rem  Sets UV to the command ("uv") or the full path of uv.exe; empty when absent.
:locate_uv
set "UV="
uv --version >nul 2>&1
if not errorlevel 1 set "UV=uv"
if defined UV goto :eof
for %%P in ("%USERPROFILE%\.local\bin\uv.exe" "%LOCALAPPDATA%\Microsoft\WinGet\Links\uv.exe") do (
    if not defined UV if exist "%%~P" set "UV=%%~P"
)
goto :eof

rem ---- subroutine: install uv (official installer, then winget) ---------------
rem  The official installer puts uv.exe in %USERPROFILE%\.local\bin and adds that
rem  folder to the user's PATH (for new consoles); this run uses the full path.
:install_uv
set "UV="
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; irm https://astral.sh/uv/install.ps1 | iex"
call :locate_uv
if defined UV goto :eof
winget --version >nul 2>&1
if errorlevel 1 goto :eof
echo [pdf2word] The installer from astral.sh failed - trying winget...
winget install --id astral-sh.uv -e --silent --accept-source-agreements --accept-package-agreements
call :locate_uv
goto :eof

rem ---- subroutine: find an installed Python %PY_TOP% (no uv) -----------------
:find_python
set "BASEPY="
py -%PY_TOP% -I -c "%PY_EXACT%" >nul 2>&1
if not errorlevel 1 set "BASEPY=py -%PY_TOP%"
if defined BASEPY goto :eof
python -I -c "%PY_EXACT%" >nul 2>&1
if not errorlevel 1 set "BASEPY=python"
goto :eof

rem ---- errors ----------------------------------------------------------------
:no_python
echo [pdf2word] ERROR: Python %PY_TOP% is not installed, and uv could not be installed to download it.
echo.
echo   To fix: make sure this PC is online and run this file again - uv is installed
echo   from https://astral.sh/uv and downloads Python %PY_TOP% by itself.  Or install one
echo   of them yourself: uv from https://docs.astral.sh/uv/ (`pip install uv` or
echo   `winget install astral-sh.uv`), or Python %PY_TOP% from https://www.python.org/downloads/
echo   with "Add python.exe to PATH" ticked.  (%PY_MAX% or newer cannot install the packages.)
goto :fail
:fail_venv
echo [pdf2word] ERROR: could not create the virtual environment at %VENV%
echo.
echo   To fix: make sure this PC is online (uv may need to download Python %PY_TOP%), check
echo   that the folder can be written, or set PDF2WORD_VENV=^<folder^> to use another location.
goto :fail
:bad_venv
set "VENV_PYVER=a Python that does not start (broken environment)"
set "VENV_PYNUM="
"%PY%" -I -c "import sys; print(sys.version.split()[0])" > "%TEMP%\pdf2word-pyver.txt" 2>nul
if not errorlevel 1 set /p VENV_PYNUM=<"%TEMP%\pdf2word-pyver.txt"
if defined VENV_PYNUM set "VENV_PYVER=Python %VENV_PYNUM%"
del "%TEMP%\pdf2word-pyver.txt" 2>nul
echo [pdf2word] ERROR: the environment %VENV%
echo [pdf2word]        uses %VENV_PYVER%, but pdf2word needs Python %PY_TOP%.
echo.
echo   To fix: delete that folder (or set PDF2WORD_VENV=^<folder^> to use another one) and
echo   run this file again - a new environment with Python %PY_TOP% is created.
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
