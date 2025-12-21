@echo off
setlocal

REM ==== Configuration ==== 
set "INPUT_DIR=%~dp0input"
set "OUTPUT_DIR=%~dp0output"

REM ==== Execution ==== 
python "%~dp0folder2pdf.py" "%INPUT_DIR%" "%OUTPUT_DIR%"

REM ==== Pause to inspect logs ==== 
pause
