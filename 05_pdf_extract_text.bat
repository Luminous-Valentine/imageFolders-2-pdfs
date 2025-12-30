@echo off
setlocal EnableExtensions

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
    echo Created "%CFG%" from example. Please edit EXTRACT_INPUT_DIR and EXTRACT_OUTPUT_DIR.
  )
)

if not "%~1"=="" goto :FROM_ARGS

set "PDF_ARGS="
if not defined PDF_ARGS (
  echo.
  echo Drag-and-drop one or more PDF files into this window, then press Enter.
  echo Or just press Enter to process EXTRACT_INPUT_DIR from tool_settings.txt (legacy: reference_paths.txt).
  echo Tip: You can also drag-and-drop a folder to process all PDFs under it.
  echo.
  set /p "PDF_ARGS=> "
)

set "LIST_FILE=%TEMP%\extract_pdf_paths_%RANDOM%_%RANDOM%.txt"

if not defined PDF_ARGS (
  python "%~dp0src\\extract_pdf_text.py" --ref "%ACTIVE_CFG%"
) else (
  > "%LIST_FILE%" (
    for %%I in (%PDF_ARGS%) do (
      <nul set /p "=%%~fI"
      echo.
    )
  )
  python "%~dp0src\\extract_pdf_text.py" --ref "%ACTIVE_CFG%" --paths-file "%LIST_FILE%"
  del "%LIST_FILE%" >nul 2>nul
)

pause
goto :EOF

:FROM_ARGS
set "LIST_FILE=%TEMP%\extract_pdf_paths_%RANDOM%_%RANDOM%.txt"
type nul > "%LIST_FILE%"
:ARG_LOOP
>> "%LIST_FILE%" <nul set /p "=%~f1"
>> "%LIST_FILE%" echo.
shift
if not "%~1"=="" goto :ARG_LOOP
python "%~dp0src\\extract_pdf_text.py" --ref "%ACTIVE_CFG%" --paths-file "%LIST_FILE%"
del "%LIST_FILE%" >nul 2>nul
pause
