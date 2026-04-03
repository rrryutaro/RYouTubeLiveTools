@echo off
:: ============================================================
:: signing_env.example.bat  —  RRoulette 署名設定テンプレート
:: ============================================================
:: このファイルをコピーして signing_env.bat などにリネームし、
:: 実際の値を埋めてから build_release.bat を実行してください。
::
:: 【重要】
::   - このファイルには秘密情報を書かないでください。
::   - 実際の設定ファイル（signing_env.bat 等）は Git 管理対象外にしてください。
::   - .gitignore に signing_env.bat を追加することを推奨します。
:: ============================================================

:: 署名を有効にする（1 = 有効、それ以外 = スキップ）
set RROULETTE_SIGN_ENABLE=1

:: コード署名証明書 (.pfx) のフルパス
:: 例: set RROULETTE_SIGN_PFX=C:\certs\my_cert.pfx
set RROULETTE_SIGN_PFX=C:\path\to\your_certificate.pfx

:: .pfx ファイルのパスワード
:: 例: set RROULETTE_SIGN_PASSWORD=your_password_here
set RROULETTE_SIGN_PASSWORD=your_pfx_password

:: タイムスタンプサービスの URL（省略時は DigiCert を使用）
:: DigiCert:   http://timestamp.digicert.com
:: Sectigo:    http://timestamp.sectigo.com
:: GlobalSign: http://timestamp.globalsign.com/scripts/timstamp.dll
set RROULETTE_SIGN_TIMESTAMP_URL=http://timestamp.digicert.com

:: ============================================================
:: 設定後、このファイルを実行してから build_release.bat を起動:
::
::   signing_env.bat && build_release.bat
::
:: または PowerShell 経由:
::
::   cmd /c "signing_env.bat && build_release.bat"
:: ============================================================
