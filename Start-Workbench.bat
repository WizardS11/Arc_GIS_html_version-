@echo off
rem Double-click to open the HPW GIS Workbench in its own window (no browser address bar).
rem Closing the workbench window also stops the GIS engine.
start "" powershell -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "%~dp0scripts\launch.ps1"
