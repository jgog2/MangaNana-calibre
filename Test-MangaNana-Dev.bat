@echo off
setlocal
title MangaNana Dev Build Tester

set "REPO=C:\MangaNana-Dev\MangaNana-calibre"
set "ZIP=%REPO%\dist\MangaNana-Calibre-dev.zip"
set "CALIBRE_CUSTOMIZE=C:\Program Files\Calibre2\calibre-customize.exe"
set "CALIBRE_DEBUG=C:\Program Files\Calibre2\calibre-debug.exe"
set "TEST_LIBRARY=C:\MangaNana-Dev\Test-Library"

cd /d "%REPO%" || (
    echo.
    echo ERROR: Could not open:
    echo %REPO%
    echo.
    pause
    exit /b 1
)

if not exist "%ZIP%" (
    echo.
    echo ERROR: Dev ZIP not found:
    echo %ZIP%
    echo.
    pause
    exit /b 1
)

if not exist "%CALIBRE_CUSTOMIZE%" (
    echo.
    echo ERROR: calibre-customize.exe not found:
    echo %CALIBRE_CUSTOMIZE%
    echo.
    pause
    exit /b 1
)

if not exist "%CALIBRE_DEBUG%" (
    echo.
    echo ERROR: calibre-debug.exe not found:
    echo %CALIBRE_DEBUG%
    echo.
    pause
    exit /b 1
)

echo ============================================================
echo MangaNana Dev Build Tester
echo ============================================================
echo.
echo Current dev ZIP SHA-256:
powershell.exe -NoProfile -Command "(Get-FileHash -LiteralPath '%ZIP%' -Algorithm SHA256).Hash"
echo.

tasklist /FI "IMAGENAME eq calibre.exe" 2>NUL | find /I "calibre.exe" >NUL
if not errorlevel 1 (
    echo Calibre is currently running.
    echo Fully close Calibre before installing the dev build.
    echo.
    pause
    exit /b 1
)

echo Installing MangaNana dev ZIP...
echo.
"%CALIBRE_CUSTOMIZE%" -a "%ZIP%"
if errorlevel 1 (
    echo.
    echo ERROR: Plugin installation failed.
    echo.
    pause
    exit /b 1
)

echo.
echo Installation succeeded.
echo Launching MangaNana test library with Google Books enabled...
echo.

set "MANGANANA_GOOGLE_BOOKS_ENABLED=1"
start "" "%CALIBRE_DEBUG%" -g -- --with-library "%TEST_LIBRARY%"

echo MangaNana test Calibre launched.
echo.
echo You can close this window.
echo.
pause
endlocal
