@echo off
chcp 65001 > nul
echo ====================================
echo  RSheetsViewer - Build EXE
echo ====================================
echo.

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

echo [Use] %PI_PATH%
echo [Build] Creating RSheetsViewer.exe...
echo.

"%PI_PATH%" RSheetsViewer.spec --clean

if errorlevel 1 (
    echo.
    echo [Error] Build failed.
    pause
    exit /b 1
)

echo.
echo ====================================
echo  Done! dist\RSheetsViewer.exe created.
echo ====================================
echo.
pause
