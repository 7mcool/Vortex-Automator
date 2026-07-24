@echo off
setlocal
cd /d "%~dp0"
if not exist "data\logs" mkdir "data\logs"
echo [%date% %time%] === SYNCHRONISATION SERMONS LONGS ===>> "data\logs\youtube-sync.log"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "scripts\sync_youtube_sources.ps1" %* >> "data\logs\youtube-sync.log" 2>&1
exit /b %ERRORLEVEL%
