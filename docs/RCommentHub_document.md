# RCommentHub

YouTube Live のコメントをリアルタイム受信・管理・表示するツール。

## バージョン

v0.1.0

## 機能概要

- YouTube Live のコメントをリアルタイム受信
- コメントの一覧表示・詳細確認・フィルタリング
- コメント種別・投稿者属性による色分け表示
- 透過オーバーレイ表示（コメント文字のみ表示、背景透過）
- テキスト読み上げ（SAPI5 / pyttsx3）
- ユーザー管理（ブラックリスト・ホワイトリスト等）
- セッションログ自動保存

## 実行方法

```bash
cd RCommentHub
python rcommenthub.py
```

YouTube Data API v3 のキーが必要です。  
初回起動後、設定画面から API キーを登録してください。

## 画面構成

**コメントビュー**（常時表示用フローティングウィンドウ）

```
┌──────────────────────────────────┐
│ ■ 接続状態  配信タイトル   [操作]│  ← 接続状態バー
├──────────────────────────────────┤
│ [全メッセージ][フィルタ][ユーザー]│  ← タブ
│                                  │
│  投稿者: コメント本文             │
│  投稿者: コメント本文             │
│                                  │
└──────────────────────────────────┘
```

右クリックで「コメント以外透過」等の操作メニューを表示。

**詳細・管理ウィンドウ**（接続・設定・詳細確認用）

接続操作、フィルタ設定、ユーザー管理、全コメント一覧などを提供。

## ファイル構成

| ファイル | 説明 |
|---|---|
| `rcommenthub.py` | アプリケーション起動・ウィンドウ間協調 |
| `comment_controller.py` | ビジネスロジック・YouTube 受信管理 |
| `comment_window.py` | コメントビュー（フローティングウィンドウ） |
| `detail_window.py` | 詳細・管理ウィンドウ |
| `connect_dialog.py` | 接続ダイアログ |
| `settings_window.py` | 設定ウィンドウ |
| `debug_sender.py` | デバッグコメント送信ウィンドウ |
| `constants.py` | 定数・カラーテーマ定義 |
| `settings_manager.py` | 設定の読み書き管理 |
| `filter_rules.py` | フィルタルール管理 |
| `user_manager.py` | ユーザー管理 |
| `session_logger.py` | セッションログ管理 |
| `log_writer.py` | ログファイル書き込み |
| `tts_service.py` | テキスト読み上げサービス |
| `tts_name.py` | 読み上げ名前処理 |
| `youtube_client.py` | YouTube Data API クライアント |
| `RCommentHub.spec` | PyInstaller ビルド設定 |

設定ファイル (`rcommenthub_settings.json`) と実行ログは自動生成されます。

## 依存ライブラリ

- Python 3.11+
- tkinter（標準ライブラリ）
- google-api-python-client（YouTube API 接続時）
- pyttsx3（テキスト読み上げ使用時）

## 既知の制限

- Windows 専用（Windows 10 / 11）
- YouTube Data API v3 のクォータ制限に依存する
