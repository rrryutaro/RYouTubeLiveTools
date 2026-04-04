@echo off
cd /d "%~dp0"
echo [RCommentHub] EXE ビルド開始...
pyinstaller RCommentHub.spec --noconfirm
echo.
if exist "dist\RCommentHub.exe" (
    echo [OK] dist\RCommentHub.exe が生成されました。
) else (
    echo [NG] dist\RCommentHub.exe が見つかりません。ビルドログを確認してください。
)
pause
