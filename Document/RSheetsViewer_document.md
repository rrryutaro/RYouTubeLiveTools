# RSheetsViewer — ドキュメント

作成日: 2026/03/29
バージョン: 1.0

---

## 概要

配信中にブラウザの余計な情報を映さず、Google スプレッドシートだけを操作するための専用GUIツールです。
PyQt6 フレームレスウィンドウ内に Chrome を Win32 `SetParent` API で埋め込む構成を採用しています。

---

## ファイル構成

| ファイル名 | 役割 |
|---|---|
| `sheets_viewer.py` | アプリ本体（Python スクリプト） |
| `sheets_viewer.spec` | PyInstaller ビルド定義ファイル |
| `build_exe.bat` | EXE ビルド用バッチファイル（**CP932 エンコード必須**） |
| `requirements.txt` | 依存パッケージ一覧 |
| `RSheetsViewer.exe` | ビルド後の実行ファイル（`dist\` フォルダに生成） |

---

## EXE のビルド方法

### 必要環境

- Windows 10 / 11
- Python 3.10 以上（3.11 推奨）
- pip（Python に同梱）
- Google Chrome（インストール済みであること）

### 手順

1. `sheets_viewer.py` と `build_exe.bat` を**同じフォルダ**に置く
2. 依存パッケージをインストール:
   ```
   pip install -r requirements.txt
   ```
3. `build_exe.bat` をダブルクリック
4. 完了後、`dist\RSheetsViewer.exe` が生成される

> **重要:** `build_exe.bat` は **Shift-JIS (CP932 + CRLF)** で保存されています。
> テキストエディタで編集する場合は必ず CP932 を選択してください。UTF-8 で保存すると文字化けして動作しなくなります。

---

## 使い方

### 初回起動

1. `RSheetsViewer.exe` を起動
2. URL 入力ダイアログが表示されるので Google スプレッドシートの URL を貼り付けて「開く」
3. Google アカウントのログインが必要な場合は自動的にログイン画面が開く

### 2回目以降

- 前回開いたスプレッドシートが自動的に開く
- ウィンドウのサイズ・位置も前回の状態が復元される

---

## 操作方法

| 操作 | 方法 |
|---|---|
| ウィンドウ移動 | ツールバーをドラッグ |
| ウィンドウリサイズ | ウィンドウ端をドラッグ |
| URL を変更 | ツールバーの「🔗 URLを変更」ボタン または `Ctrl+L` |
| 再読み込み | ツールバーの「↻」ボタン または `F5` |
| 戻る | ツールバーの「◀」ボタン |
| 進む | ツールバーの「▶」ボタン |
| 最大化 / 元に戻す | ツールバーの「□」ボタン または ツールバーをダブルクリック |
| 全画面表示 | `F11` |
| 閉じる | ツールバーの「✕」ボタン |

---

## データ保存場所

アプリのデータはすべて実行端末の `%APPDATA%\SheetsViewer\` に保存されます。
**ソースコードにはログイン情報・URL 等は一切含まれません。**

| パス | 内容 |
|---|---|
| `%APPDATA%\SheetsViewer\config.json` | 最後に開いた URL・ウィンドウ位置のみ |
| `%APPDATA%\SheetsViewer\chrome_profile\` | Chrome のログインセッション（Cookie等） |

---

## OBS での使用

「ウィンドウキャプチャ」→ キャプチャ方法「**Windows 10（1903 以降）**」で動作確認済みです。

---

## 技術情報

### アーキテクチャ

```
PyQt6 フレームレスウィンドウ
  └─ DraggableToolbar（ツールバー）
  └─ embed_area（Chrome 埋め込みエリア）
       └─ Chrome プロセス（SetParent で埋め込み）
```

### 主要クラス

| クラス名 | 役割 |
|---|---|
| `MainWindow` | メインウィンドウ、Chrome 埋め込み・リサイズ管理 |
| `ChromeLauncher` | Chrome 起動スレッド（QThread） |
| `DraggableToolbar` | ドラッグ移動対応ツールバー |
| `UrlDialog` | URL 入力ダイアログ |

### 設計上の重要な判断

| 判断 | 理由 |
|---|---|
| QtWebEngine を不採用 | Google のログインブロック対象になるため |
| `--disable-gpu` を Chrome 起動オプションに追加 | OBS で映らない問題への対処 |
| Win32 `SetParent` で Chrome を埋め込み | フレームレスな専用ビューアーとして機能させるため |
| `build_exe.bat` を CP932 で保存 | UTF-8 だと Windows cmd が文字化けするため |

---

## 既知の制限・注意事項

- **Windows 専用**（Win32 API 依存のため）
- Google Chrome がインストールされていない環境では動作しない
- Google Sheets・Google ログイン画面以外へのナビゲーションは想定外の動作になる場合がある

---

## トラブルシューティング

### 起動しない場合
```
pip install --upgrade PyQt6
```

### ログインが維持されない場合
- `%APPDATA%\SheetsViewer\chrome_profile` フォルダが存在するか確認
- アンチウイルスソフトがフォルダへの書き込みをブロックしている可能性がある

### OBS に映らない場合
- キャプチャ方法を「Windows 10（1903 以降）」に変更する
