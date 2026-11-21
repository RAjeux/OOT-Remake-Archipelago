@echo off
where py >nul 2>nul
if errorlevel 1 goto trypython
py -3 "%~dp0Observer-Archipelago.py"
goto done
:trypython
python "%~dp0Observer-Archipelago.py"
:done
pause
