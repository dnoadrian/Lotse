@echo off
rem Doppelklick: beendet Quitly (Daten bleiben erhalten)
cd /d "%~dp0"
docker compose stop
pause
