@echo off
rem Doppelklick: startet Quitly und oeffnet https://quitly.at
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\quitly-start.ps1"
if errorlevel 1 pause
