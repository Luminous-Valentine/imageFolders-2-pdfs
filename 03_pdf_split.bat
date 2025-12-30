@echo off
setlocal EnableExtensions

rem Ensure Japanese text renders better on modern Windows terminals.
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

cd /d "%~dp0"

set "CFG=%~dp0tool_settings.txt"
set "LEGACY_CFG=%~dp0reference_paths.txt"
set "EXAMPLE_CFG=%~dp0tool_settings.example.txt"

set "ACTIVE_CFG=%CFG%"
if not exist "%CFG%" (
  if exist "%LEGACY_CFG%" (
    set "ACTIVE_CFG=%LEGACY_CFG%"
  ) else (
    copy "%EXAMPLE_CFG%" "%CFG%" >nul
    echo Created "%CFG%" from example. Please edit OCR_DIR and SPLIT_OUTPUT_DIR if needed.
  )
)

if not "%~1"=="" goto :FROM_ARGS

set "DROP_ARGS="
if not defined DROP_ARGS (
  echo.
  echo Drag-and-drop one or more PDF files into this window, then press Enter.
  echo Tip: You can also drag-and-drop folders (PDFs directly under them are processed).
  echo.
  set /p "DROP_ARGS=> "
)

set "LIST_FILE=%TEMP%\split_pdf_paths_%RANDOM%_%RANDOM%.txt"

if not defined DROP_ARGS (
  python "%~dp0src\\split_pdf.py" --ref "%ACTIVE_CFG%"
) else (
  > "%LIST_FILE%" (
    for %%I in (%DROP_ARGS%) do (
      <nul set /p "=%%~fI"
      echo.
    )
  )
  python "%~dp0src\\split_pdf.py" --ref "%ACTIVE_CFG%" --paths-file "%LIST_FILE%"
  del "%LIST_FILE%" >nul 2>nul
)

pause
goto :EOF

:FROM_ARGS
set "LIST_FILE=%TEMP%\split_pdf_paths_%RANDOM%_%RANDOM%.txt"
type nul > "%LIST_FILE%"
:ARG_LOOP
>> "%LIST_FILE%" <nul set /p "=%~f1"
>> "%LIST_FILE%" echo.
shift
if not "%~1"=="" goto :ARG_LOOP
python "%~dp0src\\split_pdf.py" --ref "%ACTIVE_CFG%" --paths-file "%LIST_FILE%"
del "%LIST_FILE%" >nul 2>nul
pause
