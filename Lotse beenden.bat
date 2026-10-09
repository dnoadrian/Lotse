@echo off
rem Doppelklick: beendet Lotse (Daten bleiben erhalten)
cd /d "%~dp0"
docker compose stop
pause
