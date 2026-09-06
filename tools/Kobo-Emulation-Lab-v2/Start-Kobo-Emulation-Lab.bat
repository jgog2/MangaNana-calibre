@echo off
setlocal
title MangaNana Kobo Emulation Lab v2
set "CALIBRE_DEBUG=C:\Program Files\Calibre2\calibre-debug.exe"
set "SCRIPT=%~dp0kobo_emulation_lab_v2.py"

if not exist "%CALIBRE_DEBUG%" (
    echo ERROR: calibre-debug.exe not found:
    echo %CALIBRE_DEBUG%
    echo.
    pause
    exit /b 1
)

"%CALIBRE_DEBUG%" "%SCRIPT%"
if errorlevel 1 (
    echo.
    echo The Kobo Emulation Lab exited with an error.
    pause
)
endlocal
