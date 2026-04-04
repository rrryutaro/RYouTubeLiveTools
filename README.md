# RYouTubeLiveTools

YouTubeライブ配信で活用できるツール集です。
各ツールはWindows用の単体EXEとして配布します。

---

## ツール一覧

| ツール | フォルダ | 概要 |
|---|---|---|
| [RTokei](RTokei/) | `RTokei/` | デスクトップ常駐デジタル時計。最前面表示・背景透過・スナップ対応 |
| [RSheetsViewer](RSheetsViewer/) | `RSheetsViewer/` | 配信中にブラウザの余計な情報を映さずGoogleスプレッドシートを操作するツール |
| [RRoulette](RRoulette/) | `RRoulette/` | YouTubeライブ配信向けルーレットツール。背景透過・OBSキャプチャ対応 |
| [RCommentHub](RCommentHub/) | `RCommentHub/` | YouTubeライブのコメントをリアルタイム受信・表示・管理するツール。YouTube Data API v3 キーが必要 |

---

## OBSでの使用について

各ツールはOBSの**ウィンドウキャプチャ**でキャプチャできます。

### 背景透過をOBSに反映する場合

ツールの背景透過機能をOBSキャプチャにも反映させるには、OBS側のキャプチャ方法の設定が必要です。

1. OBSのソース一覧でウィンドウキャプチャソースを右クリック →「プロパティ」を開く
2. **「キャプチャ方法」を「Windows 10 (1903以降)」に変更**する
3. 「OK」で閉じる

> この設定はWindows 10 バージョン1903以降・Windows 11 で使用できます。
> 「BitBlt」など他のキャプチャ方法では背景透過がOBSに反映されません。
>
> **動作確認バージョン**: OBS Studio 32.1.0 (64 bit)
> 他のバージョンでは設定項目の名称・位置が異なる場合があります。

背景透過機能を持つツール: **RTokei**・**RRoulette**

---

## 動作環境

- Windows 10 / 11
- 各ツールはEXEとして配布しているため、Python不要で使用可能

---

## ビルド方法

ソースからEXEをビルドする場合は各ツールフォルダの `README.md` を参照してください。

共通要件:
- Python 3.9 以上
- PyInstaller

---

## ライセンス

[MIT License](LICENSE)
