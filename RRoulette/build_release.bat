@echo off
chcp 65001 > nul
echo ====================================
echo  RRoulette - Release Build
echo  (EXE build + optional signing)
echo ====================================
echo.

:: ----------------------------------------
:: Step 1: Find PyInstaller
:: ----------------------------------------
for /f "delims=" %%i in ('python -c "import sys,os; print(os.path.join(os.path.dirname(sys.executable), 'Scripts', 'pyinstaller.exe'))" 2^>nul') do set PI_PATH=%%i

if not exist "%PI_PATH%" (
    for /f "delims=" %%i in ('python -c "import site,os; print(os.path.join(site.getusersitepackages().replace('site-packages',''), 'Scripts', 'pyinstaller.exe'))" 2^>nul') do set PI_PATH=%%i
)

if not exist "%PI_PATH%" (
    echo [Install] Installing PyInstaller...
    pip install pyinstaller
    for /f "delims=" %%i in ('python -c "import sys,os; print(os.path.join(os.path.dirname(sys.executable), 'Scripts', 'pyinstaller.exe'))" 2^>nul') do set PI_PATH=%%i
)

if not exist "%PI_PATH%" (
    echo [Error] pyinstaller.exe not found.
    echo Please run manually: pip install pyinstaller
    pause
    exit /b 1
)

:: ----------------------------------------
:: Step 2: Build EXE
:: ----------------------------------------
echo [Build] Creating RRoulette.exe...
echo.

"%PI_PATH%" RRoulette.spec --clean

if errorlevel 1 (
    echo.
    echo [Error] Build failed.
    pause
    exit /b 1
)

echo.
echo [Build] dist\RRoulette.exe created.
echo.

:: ----------------------------------------
:: Step 3: Optional code signing
:: ----------------------------------------
echo ====================================
echo  Signing Check
echo ====================================

if not "%RROULETTE_SIGN_ENABLE%"=="1" (
    echo [Sign] RROULETTE_SIGN_ENABLE is not set to 1.
    echo [Sign] Skipping signing.
    echo.
    echo [WARNING] This build is UNSIGNED.
    echo           Users downloading this exe from GitHub Releases
    echo           may see a Windows SmartScreen warning.
    echo           To enable signing, set environment variables and
    echo           re-run this script. See signing_env.example.bat.
    echo.
    goto :done_unsigned
)

:: Find signtool.exe
set SIGNTOOL=
for /f "delims=" %%i in ('where signtool.exe 2^>nul') do (
    if not defined SIGNTOOL set SIGNTOOL=%%i
)

if not defined SIGNTOOL (
    :: Try common Windows SDK paths
    for %%v in (10.0.22621.0 10.0.22000.0 10.0.19041.0 10.0.18362.0) do (
        if not defined SIGNTOOL (
            if exist "C:\Program Files (x86)\Windows Kits\10\bin\%%v\x64\signtool.exe" (
                set SIGNTOOL=C:\Program Files (x86)\Windows Kits\10\bin\%%v\x64\signtool.exe
            )
        )
    )
)

if not defined SIGNTOOL (
    echo [Sign] signtool.exe not found in PATH or Windows SDK.
    echo [Sign] Skipping signing.
    echo.
    echo [WARNING] This build is UNSIGNED.
    echo           signtool.exe is required for code signing.
    echo           Install Windows SDK or add signtool.exe to PATH.
    echo.
    goto :done_unsigned
)

echo [Sign] Using signtool: %SIGNTOOL%

:: Check required signing variables
if "%RROULETTE_SIGN_PFX%"=="" (
    echo [Sign] RROULETTE_SIGN_PFX is not set.
    echo [Sign] Skipping signing.
    echo.
    echo [WARNING] This build is UNSIGNED.
    echo           Set RROULETTE_SIGN_PFX to the path of your .pfx file.
    echo           See signing_env.example.bat for required variables.
    echo.
    goto :done_unsigned
)

if "%RROULETTE_SIGN_PASSWORD%"=="" (
    echo [Sign] RROULETTE_SIGN_PASSWORD is not set.
    echo [Sign] Skipping signing.
    echo.
    echo [WARNING] This build is UNSIGNED.
    echo           Set RROULETTE_SIGN_PASSWORD for the .pfx file.
    echo           See signing_env.example.bat for required variables.
    echo.
    goto :done_unsigned
)

:: Set default timestamp URL if not specified
if "%RROULETTE_SIGN_TIMESTAMP_URL%"=="" (
    set RROULETTE_SIGN_TIMESTAMP_URL=http://timestamp.digicert.com
    echo [Sign] RROULETTE_SIGN_TIMESTAMP_URL not set. Using default: %RROULETTE_SIGN_TIMESTAMP_URL%
)

:: Execute signing
echo [Sign] Signing dist\RRoulette.exe ...
echo [Sign]   PFX: %RROULETTE_SIGN_PFX%
echo [Sign]   Timestamp: %RROULETTE_SIGN_TIMESTAMP_URL%
echo.

"%SIGNTOOL%" sign ^
    /fd SHA256 ^
    /f "%RROULETTE_SIGN_PFX%" ^
    /p "%RROULETTE_SIGN_PASSWORD%" ^
    /tr "%RROULETTE_SIGN_TIMESTAMP_URL%" ^
    /td SHA256 ^
    /v ^
    dist\RRoulette.exe

if errorlevel 1 (
    echo.
    echo [Error] Signing failed. Check the error above.
    echo [WARNING] The exe was built but is UNSIGNED.
    echo           Users may see a SmartScreen warning.
    pause
    exit /b 1
)

echo.
echo [Sign] Verifying signature...

"%SIGNTOOL%" verify /pa /v dist\RRoulette.exe

if errorlevel 1 (
    echo.
    echo [Warning] Signature verification failed.
    echo           The exe may not be trusted by Windows.
    echo.
) else (
    echo.
    echo [Sign] Signature verified successfully.
    echo [Sign] dist\RRoulette.exe is SIGNED.
    echo.
)

goto :done_signed

:done_unsigned
echo ====================================
echo  Release Build Complete (UNSIGNED)
echo ====================================
echo.
echo  dist\RRoulette.exe is ready.
echo  NOTE: This is an unsigned build.
echo        SmartScreen warning may appear on first run.
echo.
pause
exit /b 0

:done_signed
echo ====================================
echo  Release Build Complete (SIGNED)
echo ====================================
echo.
echo  dist\RRoulette.exe is signed and ready for release.
echo.
pause
exit /b 0
