@echo off
setlocal
set PYTHONDONTWRITEBYTECODE=1
cd /d "%~dp0"
set "PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    echo Local build environment not found. Run build_portable.cmd first.
    exit /b 1
)
"%PYTHON%" -B -m unittest discover -s tests -v
