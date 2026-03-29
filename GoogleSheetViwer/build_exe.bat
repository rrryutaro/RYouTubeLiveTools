@echo off
echo ====================================
echo  Sheets Viewer - exeビルド
echo ====================================
echo.

:: PyInstallerの実行ファイルをPythonのScriptsフォルダから探す
for /f "delims=" %%i in ('python -c "import sys,os; print(os.path.join(os.path.dirname(sys.executable), 'Scripts', 'pyinstaller.exe'))" 2^>nul') do set PI_PATH=%%i

:: 見つからない場合はLocalAppDataのScriptsも確認
if not exist "%PI_PATH%" (
    for /f "delims=" %%i in ('python -c "import site,os; print(os.path.join(site.getusersitepackages().replace('site-packages',''), 'Scripts', 'pyinstaller.exe'))" 2^>nul') do set PI_PATH=%%i
)

:: それでも見つからなければインストール
if not exist "%PI_PATH%" (
    echo [インストール中] PyInstaller をインストールします...
    pip install pyinstaller
    for /f "delims=" %%i in ('python -c "import sys,os; print(os.path.join(os.path.dirname(sys.executable), 'Scripts', 'pyinstaller.exe'))" 2^>nul') do set PI_PATH=%%i
)

if not exist "%PI_PATH%" (
    echo [エラー] pyinstaller.exe が見つかりません。
    echo 手動で以下を実行してください: pip install pyinstaller
    pause
    exit /b 1
)

echo [使用] %PI_PATH%
echo [ビルド開始] SheetsViewer.exe を作成します...
echo.

"%PI_PATH%" sheets_viewer.spec --clean

if errorlevel 1 (
    echo.
    echo [エラー] ビルドに失敗しました。
    pause
    exit /b 1
)

echo.
echo ====================================
echo  完了！
echo  dist\SheetsViewer.exe が作成されました
echo ====================================
echo.
pause
