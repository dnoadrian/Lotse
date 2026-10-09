@echo off
rem Doppelklick: startet Lotse und oeffnet https://lotse.at
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\lotse-start.ps1"
if errorlevel 1 pause
