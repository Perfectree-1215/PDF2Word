@echo off
rem pdf2word launcher. Double-click: GUI (no console). With arguments: command line.
setlocal
set "HERE=%~dp0"
if exist "%HERE%.venv\Scripts\python.exe" (
    set "PY=%HERE%.venv\Scripts\python.exe"
    set "PYW=%HERE%.venv\Scripts\pythonw.exe"
) else (
    set "PY=python"
    set "PYW=pythonw"
)
if "%~1"=="" (
    start "" "%PYW%" "%HERE%main_gui.py"
) else (
    "%PY%" "%HERE%main_gui.py" %*
)
endlocal
