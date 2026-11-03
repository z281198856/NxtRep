@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\Stop-Local.ps1" %*
set "NXTREP_EXIT_CODE=%ERRORLEVEL%"
if not "%NXTREP_EXIT_CODE%"=="0" pause
exit /b %NXTREP_EXIT_CODE%
