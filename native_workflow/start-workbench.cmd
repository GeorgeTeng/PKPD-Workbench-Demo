@echo off
rem Starts the PMB Translational PK/PD workbench at http://127.0.0.1:8767/ . Close this window to stop it.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0backend\research_pipeline\start-workbench.ps1" %*
