@echo off
setlocal
where py >nul 2>nul
if errorlevel 1 goto trypython
py -3 "%~dp0Client-OOT-Remake.pyz" --native-install %*
goto finished
:trypython
python "%~dp0Client-OOT-Remake.pyz" --native-install %*
:finished
pause
