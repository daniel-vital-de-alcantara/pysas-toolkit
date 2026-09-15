@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
  py -3 -c "import sys; sys.exit(sys.version_info < (3,10))" >nul 2>nul
  if not errorlevel 1 (
    py -3 "%~dp0pysas_ui.py" %*
    goto end
  )
)
where python >nul 2>nul
if not errorlevel 1 (
  python -c "import sys; sys.exit(sys.version_info < (3,10))" >nul 2>nul
  if not errorlevel 1 (
    python "%~dp0pysas_ui.py" %*
    goto end
  )
)
echo Python 3.10 or newer was not found.
echo Install your approved Python distribution and try again.
echo See START_HERE.txt for requirements.
:end
if errorlevel 1 pause
endlocal
