@echo off
setlocal EnableExtensions

rem Ensure Japanese text renders better on modern Windows terminals.
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp001_run_folder2pdf_menu.ps1"

pause
