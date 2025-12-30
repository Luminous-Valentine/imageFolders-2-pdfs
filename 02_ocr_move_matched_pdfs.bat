@echo off
setlocal

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp002_run_move_matched_pdfs.ps1"

pause
