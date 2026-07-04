# RYouTubeLiveTools プライバシーポリシー

最終更新日: 2026年7月4日

言語: [English](privacy-policy.md) | 日本語

## 対象範囲

RYouTubeLiveTools は、ライブ配信支援を目的とした Windows デスクトップツール群です。本プライバシーポリシーは、このリポジトリに含まれるツールに適用されます。

YouTube API Services を利用するのは RCommentHub のみです。RCommentHub は、YouTube Live のライブチャットメッセージを取得、表示、フィルタリング、ログ保存、読み上げするためのデスクトップツールです。このリポジトリに含まれる他のツールは、YouTube API Services を直接利用しません。RRoulette は、ユーザーが機能を有効にした場合に限り、RCommentHub からローカル連携経由でコメント関連データを受け取ることがあります。

## YouTube API Services と認証

RCommentHub は、YouTube Live チャットを表示するために必要な情報を取得する目的で、ライブチャット関連 API を含む YouTube Data API v3 を利用します。ユーザーが設定した場合、RCommentHub は Google OAuth を使用して認証します。要求する Google OAuth スコープは次の通りです。

- `https://www.googleapis.com/auth/youtube.readonly`

RCommentHub は、公開データへのアクセスや互換性維持のために、API キーモードをサポートする場合があります。

Google サービスにおける情報の取り扱いについては、[Google Privacy Policy](https://policies.google.com/privacy) を参照してください。

## RCommentHub がアクセスする可能性のある情報

YouTube Live と連携して RCommentHub を使用する場合、RCommentHub は YouTube API Services を通じて、次の情報にアクセスまたは処理する可能性があります。

- YouTube Live のチャットメッセージ
- チャット投稿者の表示名
- チャットメッセージ本文
- メッセージ ID とタイムスタンプ
- 投稿者のチャンネル ID、チャンネル URL、プロフィール画像 URL、配信者、モデレーター、メンバー、認証済みなどの公開チャット権限フラグ
- ライブ配信 ID、動画 ID、ライブチャット ID、チャンネル ID、配信タイトル、その他ライブチャットへの接続と処理に必要な情報
- 認証に必要な OAuth アクセストークンとリフレッシュトークン

RCommentHub は、動画のアップロード、チャンネルデータの変更、チャットメッセージの投稿、YouTube アカウントの管理を行う権限を要求しません。

## 情報の利用目的

RCommentHub は、上記の情報をユーザー向けのライブ配信支援機能を提供する目的に限って利用します。主な利用目的は次の通りです。

- YouTube Live チャットの取得
- RCommentHub の画面上でのコメント表示
- OBS などの配信ソフト向けオーバーレイ表示
- ローカルの音声読み上げ機能によるコメント読み上げ
- コメントおよびチャット投稿者のフィルタリング、検索、管理
- ユーザー自身による確認のためのローカルセッションログ保存
- ユーザーが RRoulette 連携を有効にした場合の、`127.0.0.1` 経由での一致コメントデータ送信
- API 使用状況、通信経路、接続エラーなどのローカル診断情報の記録

## ローカル保存

RCommentHub はデスクトップアプリケーションです。データはユーザーのローカル PC に保存されます。

- OAuth トークンは、RCommentHub の実行時フォルダ内の `token.json` にローカル保存されます。
- ユーザー設定は `rcommenthub_settings.json` にローカル保存されます。
- API キーを使用する場合、設定ファイル内に Windows DPAPI で暗号化してローカル保存されます。
- ライブチャットのセッションログは、`logs/sessions/` 配下にローカル保存される場合があります。これには `session_meta.json`、`comments.jsonl`、任意のユーザースナップショットが含まれる場合があります。
- ローカル診断ログは `logs/` 配下に保存される場合があります。
- ユーザーが用意した `client_secrets.json` などの OAuth クライアント設定ファイルはローカルに残ります。

開発者は、RCommentHub の OAuth トークン、YouTube Live チャットメッセージ、チャット投稿者データ、ローカルセッションログを受信または保存するサーバーを運用していません。

## データ共有

RCommentHub はユーザーデータを販売しません。RCommentHub は、広告、分析、データ仲介、信用評価、監視目的のためにユーザーデータを第三者へ提供しません。

RCommentHub は、YouTube Live チャット機能を提供するために必要な範囲で Google および YouTube の API と通信します。ユーザーが任意の連携機能を有効にした場合、RCommentHub は `127.0.0.1` 上の RRoulette などのローカルツールと通信する場合があります。ユーザーが任意の Twitch 関連機能を設定した場合、その機能は Twitch API と通信し、Twitch トークンをローカルに保存します。

## Google API Services User Data Policy

RCommentHub における Google API から取得した情報の利用および転送は、Limited Use requirements を含む [Google API Services User Data Policy](https://developers.google.com/terms/api-services-user-data-policy) に準拠します。

Google API から取得した情報は、RCommentHub 上で明確に表示されるユーザー向け機能の提供または改善のためにのみ使用されます。ユーザーの設定および同意に基づいて当該ユーザー向け機能を提供するために必要な場合、セキュリティ目的、適用法令の遵守、または Google API Services User Data Policy で認められる場合を除き、情報は転送されません。

## アクセス権の取り消し

ユーザーは、[Google Account Permissions](https://myaccount.google.com/permissions) から、いつでも RCommentHub に付与した Google アカウントへのアクセス権を取り消すことができます。

また、RCommentHub の実行時フォルダにある `token.json`、設定ファイル、ログフォルダを削除することで、ローカルの RCommentHub データを削除できます。

## セキュリティ

RCommentHub はデータをローカルに保存するため、ユーザーは自身の PC と RCommentHub の実行時フォルダへのアクセスを保護する責任があります。ローカルのトークン、設定、ログ、OAuth クライアント設定ファイルには重要な情報が含まれる場合があるため、内容を理解せずに他者と共有しないでください。

## 問い合わせ先

質問、プライバシーに関する連絡、問題報告は GitHub Issues からお願いします。

https://github.com/rrryutaro/RYouTubeLiveTools/issues

## 変更

RYouTubeLiveTools におけるデータのアクセス、利用、保存、共有方法が変更された場合、本ポリシーを更新することがあります。
