# RCommentHub 初期設定ガイド — Google Cloud / YouTube Data API v3

このガイドでは、RCommentHub で YouTube ライブチャットを受信するために必要な  
Google Cloud プロジェクトの作成と YouTube Data API v3 の認証情報セットアップ手順を説明します。

---

## 1. この資料で行うこと

1. Google Cloud プロジェクトを新規作成する
2. YouTube Data API v3 を有効化する
3. OAuth 2.0 認証情報（クライアント ID）を作成し、`client_secrets.json` をダウンロードする
4. `client_secrets.json` を RCommentHub と同じフォルダに配置する
5. RCommentHub の設定画面から Google アカウントで認証する

---

## 2. 事前に必要なもの

| 必要なもの | 説明 |
|---|---|
| Google アカウント | YouTube チャンネルのオーナーまたは管理者のアカウント |
| Web ブラウザ | Google Cloud Console を操作するため |
| RCommentHub | セットアップ済みの実行ファイルまたは起動可能な状態 |

---

## 3. Google Cloud プロジェクトを作成する

1. ブラウザで **[Google Cloud Console](https://console.cloud.google.com/)** を開く
2. 右上の Google アカウントでログインする
3. 画面上部のプロジェクト選択メニューをクリックし、「**新しいプロジェクト**」を選択する
4. プロジェクト名を入力する（例: `RCommentHub`）
5. 「**作成**」をクリックする
6. 作成したプロジェクトが選択されていることを確認する

> **ヒント**: プロジェクトは YouTube Data API v3 の利用単位です。  
> 個人利用なら 1 プロジェクトで十分です。

---

## 4. YouTube Data API v3 を有効化する

1. 左上のメニュー（≡）から「**API とサービス**」→「**ライブラリ**」を開く
2. 検索ボックスに「`YouTube Data API v3`」と入力する
3. 検索結果から「**YouTube Data API v3**」をクリックする
4. 「**有効にする**」ボタンをクリックする
5. 「有効」と表示されたら完了

---

## 5. OAuth 同意画面を設定する

OAuth 認証を使うには、同意画面（アプリの説明画面）の設定が必要です。

1. 「**API とサービス**」→「**OAuth 同意画面**」を開く
2. User Type を「**外部**」に設定して「作成」をクリックする
3. 必須項目を入力する:
   - アプリ名: 任意（例: `RCommentHub`）
   - ユーザーサポートメール: 自分のメールアドレス
   - デベロッパーの連絡先情報: 自分のメールアドレス
4. 「**保存して次へ**」を繰り返しクリックして完了させる
5. 公開ステータスは「**テスト**」のままでよい

> **「テスト」ステータスでの制限**: テストユーザーとして登録したアカウントのみが認証できます。  
> 自分のアカウントを使う場合は、「テストユーザー」欄に自分のメールアドレスを追加してください。

---

## 6. OAuth 2.0 クライアント ID を作成する

1. 「**API とサービス**」→「**認証情報**」を開く
2. 「**認証情報を作成**」→「**OAuth クライアント ID**」をクリックする
3. アプリケーションの種類で「**デスクトップ アプリ**」を選択する
4. 名前を入力する（例: `RCommentHub Desktop`）
5. 「**作成**」をクリックする
6. 作成完了のダイアログが表示されたら「**JSON をダウンロード**」をクリックする
7. ダウンロードしたファイルの名前を **`client_secrets.json`** に変更する

> **注意**: このファイルはあなたの認証情報です。他人へ渡したり、GitHub や SNS に公開したりしないでください。

---

## 7. RCommentHub へ設定する

### 7-1. client_secrets.json の配置

1. `client_secrets.json` を **RCommentHub の実行ファイル（.exe）と同じフォルダ** にコピーする

```
例:
  C:\Tools\RCommentHub\
    RCommentHub.exe
    client_secrets.json   ← ここに配置
```

### 7-2. RCommentHub から Google アカウントで認証する

1. RCommentHub を起動する
2. 右クリックメニューまたはボタンから「**設定**」を開く
3. 「**API**」タブを開く
4. `client_secrets.json: ロード済み` と表示されていることを確認する  
   （「未ロード」と表示される場合は配置場所を確認してください）
5. 「**Googleアカウントで認証する**」ボタンをクリックする
6. ブラウザが開き、Google ログイン画面が表示される
7. YouTube チャンネルのオーナーアカウントでログインする
8. 「このアプリはテストモードです」と表示される場合は「続行」をクリックする
9. アクセス許可画面で「**許可**」をクリックする
10. ブラウザに「認証が完了しました」と表示されたら RCommentHub に戻る
11. ステータスが「認証済み」に変わっていれば完了

> **認証情報の保存先**: 認証情報（`token.json`）はアプリと同じフォルダ内にのみ保存されます。  
> 開発者のサーバーへは送信されません。

---

## 8. APIキー方式と OAuth 方式の違い

| | APIキー方式 | OAuth 2.0 方式 |
|---|---|---|
| 使える操作 | 公開データのみ | 認証ユーザーのデータ（ライブチャット含む） |
| ライブチャット取得 | 公開配信のみ・制限あり | 自分のチャンネルを含むチャット取得 |
| RCommentHub UI | 現バージョンでは設定画面なし | 「Googleアカウントで認証する」ボタン |
| セキュリティ | キーが漏洩するとリスク | アクセストークンで管理 |

> **現在の RCommentHub**: OAuth 2.0 方式を主要サポートとしています。  
> 通常は OAuth 方式でセットアップしてください。

---

## 9. クォータと利用量の注意

YouTube Data API v3 はリクエスト数に上限（クォータ）があります。

- 公式ドキュメントでのデフォルト割り当ては **1 日あたり 10,000 ユニット** とされています（将来変更される可能性があります）
- API リクエストごとにコスト（ユニット数）が消費されます
- RCommentHub は無駄なリクエストを避ける設計で動作します

**クォータ使用量の確認方法**:

1. Google Cloud Console を開く
2. 「API とサービス」→「ダッシュボード」→「YouTube Data API v3」を選択する
3. 「割り当て」タブで使用量を確認できる

> 1 日のクォータを超過すると、その日はコメント取得ができなくなります。  
> 通常の個人利用では超過しない場合がほとんどですが、高頻度ポーリングや長時間配信では注意が必要です。

---

## 10. 請求先アカウント・無料トライアル表示についての注意

Google Cloud Console を使っていると、以下のような案内が表示される場合があります。

- 「無料トライアルを開始」
- 「請求先アカウントを作成してください」
- 「Always Free」

**これらの表示について**:

- これらは Google Cloud 全体のサービス（Compute Engine、Cloud Storage 等）向けの案内として表示されることがあります
- YouTube Data API v3 の利用はクォータ制で管理され、利用状況はダッシュボードで確認できます
- 実際に請求先アカウントが必要かどうか、無料枠やAlways Freeの対象になるかは、Google Cloud Console の現在の表示と [Google 公式ドキュメント](https://cloud.google.com/free) を確認してください

> **注意**: 「RCommentHub に不要なサービス」（Compute Engine、Cloud Storage、BigQuery 等）を有効化したり、課金が発生しそうなリソースを作成したりしないでください。

---

## 11. よくあるトラブル

### `client_secrets.json: 未ロード` と表示される

- ファイルが RCommentHub.exe と同じフォルダにあるか確認する
- ファイル名が正確に `client_secrets.json` であるか確認する（拡張子に注意）
- ダウンロード時のファイル名が異なる場合は手動で変更する

### 認証ボタンを押してもブラウザが開かない

- ブラウザがデフォルトブラウザとして設定されているか確認する
- セキュリティソフトがポートを遮断していないか確認する
- RCommentHub を管理者として起動してみる

### 「このアプリは確認されていません」と表示される

- OAuth 同意画面のステータスが「テスト」の場合、この警告が表示されます
- 「詳細」→「(アプリ名) に移動」をクリックして続行できます
- テストユーザーに自分のメールアドレスが登録されているか確認する

### コメントが取得できない

- YouTube Data API v3 が有効化されているか確認する
- 認証ステータスが「認証済み」になっているか確認する
- クォータを超過していないか Google Cloud Console で確認する
- 配信が実際にライブ配信中（プレミア公開ではない）か確認する

---

## 12. してはいけないこと

- `client_secrets.json` を GitHub や SNS、配信画面に映さない
- `token.json` を他人に渡さない
- API キーや認証情報を公開の場所に書かない
- RCommentHub に不要な Google Cloud サービス（Compute Engine 等）を有効化しない
- 不審なサイトやツールに `client_secrets.json` を入力・アップロードしない

---

## 13. 用語ミニ解説

| 用語 | 説明 |
|---|---|
| Google Cloud Console | Google の API やサービスを管理するウェブ画面 |
| プロジェクト | API 利用の管理単位。API キーやクォータはプロジェクトごとに管理される |
| YouTube Data API v3 | YouTube のデータ（動画・チャンネル・ライブチャット等）を取得するための Google の API |
| OAuth 2.0 | ユーザーが「このアプリに自分のデータへのアクセスを許可する」ための認証方式 |
| クライアント ID / client_secrets.json | アプリ（RCommentHub）が「どのアプリか」を Google に証明するための情報 |
| トークン / token.json | 認証後に発行される「認証証明書」。有効期限があり、自動でリフレッシュされる |
| クォータ | API 利用の上限数。YouTube Data API v3 は 1 日あたりの上限が設定されている |
| ユニット | クォータの消費単位。リクエストの種類によって消費量が異なる |

---

## 関連リンク

- [YouTube Data API v3 概要 (Google)](https://developers.google.com/youtube/v3/getting-started?hl=ja)
- [Google Cloud Console](https://console.cloud.google.com/)
- [OAuth 2.0 for Desktop Apps (Google)](https://developers.google.com/identity/protocols/oauth2/native-app?hl=ja)
- [YouTube Data API v3 クォータと使用制限 (Google)](https://developers.google.com/youtube/v3/getting-started?hl=ja#quota)
