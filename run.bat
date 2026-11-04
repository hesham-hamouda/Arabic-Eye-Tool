@echo off
REM Arabic Eye Tool - the ONLY launcher. Double-click this file.
REM Desktop window: app menu + Read + chat. No console needed.
cd /d "%~dp0app"
start "Arabic Eye Tool" pythonw.exe desktop_eye.py
