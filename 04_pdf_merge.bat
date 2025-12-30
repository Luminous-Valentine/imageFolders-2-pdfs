@echo off
setlocal EnableExtensions

rem Ensure Japanese text renders better on modern Windows terminals.
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

cd /d "%~dp0"

if not "%~1"=="" goto :FROM_ARGS

python "%~dp0src\\merge_pdf.py"

pause
goto :EOF

:FROM_ARGS
set "LIST_FILE=%TEMP%\merge_pdf_paths_%RANDOM%_%RANDOM%.txt"
type nul > "%LIST_FILE%"
:ARG_LOOP
>> "%LIST_FILE%" <nul set /p "=%~f1"
>> "%LIST_FILE%" echo.
shift
if not "%~1"=="" goto :ARG_LOOP
python "%~dp0src\\merge_pdf.py" --paths-file "%LIST_FILE%" --interactive
del "%LIST_FILE%" >nul 2>nul
pause

