@echo off
title Branch of the Future
cd /d "%~dp0"

REM Background watcher: waits for Flask to bind port 5000, then opens the browser.
start "" /b powershell -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "%~dp0_browser-launcher.ps1"

call "%~dp0run.bat"
