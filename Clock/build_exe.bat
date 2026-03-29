@echo off
echo ====================================
echo  RTokei - exeビルド
echo ====================================
echo.

for /f "delims=" %%i in ('python -c "import sys,os; print(os.path.join(os.path.dirname(sys.executable), 'Scripts', 'pyinstaller.exe'))" 2^>nul') do set PI_PATH=%%i

if not exist "%PI_PATH%" (
    for /f "delims=" %%i in ('python -c "import site,os; print(os.path.join(site.getusersitepackages().replace('site-packages',''), 'Scripts', 'pyinstaller.exe'))" 2^>nul') do set PI_PATH=%%i
)

if not exist "%PI_PATH%" (
    echo [Install] PyInstaller をインストールします...
    pip install pyinstaller
    for /f "delims=" %%i in ('python -c "import sys,os; print(os.path.join(os.path.dirname(sys.executable), 'Scripts', 'pyinstaller.exe'))" 2^>nul') do set PI_PATH=%%i
)

if not exist "%PI_PATH%" (
    echo [Error] pyinstaller.exe が見つかりません。
    echo 手動で実行してください: pip install pyinstaller
    pause
    exit /b 1
)

echo [Use] %PI_PATH%
echo [Build] RTokei.exe を作成します...
echo.

"%PI_PATH%" --onefile --noconsole --name "RTokei" clock.py --clean

if errorlevel 1 (
    echo.
    echo [Error] ビルドに失敗しました。
    pause
    exit /b 1
)

echo.
echo ====================================
echo  完了！ dist\RTokei.exe が作成されました
echo ====================================
echo.
pause
