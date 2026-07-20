@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0load.ps1" %*
exit /b %errorlevel%
