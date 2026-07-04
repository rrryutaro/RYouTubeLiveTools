# RYouTubeLiveTools Privacy Policy

Last updated: July 4, 2026

Language: English | [日本語](privacy-policy.ja.md)

## Scope

RYouTubeLiveTools is a collection of Windows desktop tools for live streaming support. This Privacy Policy applies to the tools in this repository.

Only RCommentHub uses YouTube API Services. RCommentHub is a desktop tool for receiving, displaying, filtering, logging, and reading aloud live chat messages from YouTube Live streams. Other tools in this repository do not directly use YouTube API Services. RRoulette can optionally receive comment-related data from RCommentHub through a local integration when the user enables that feature.

## YouTube API Services and Authentication

RCommentHub uses YouTube Data API v3, including live chat related APIs, to retrieve information needed to display YouTube Live chat. RCommentHub uses Google OAuth for authentication when configured by the user. The requested Google OAuth scope is:

- `https://www.googleapis.com/auth/youtube.readonly`

RCommentHub may also support an API key mode for public data access and compatibility.

Google's handling of information in Google services is described in the [Google Privacy Policy](https://policies.google.com/privacy).

## Information RCommentHub May Access

When you use RCommentHub with YouTube Live, the tool may access or process the following information through YouTube API Services:

- YouTube Live chat messages
- Chat author display names
- Chat message text
- Message IDs and timestamps
- Author channel IDs, channel URLs, profile image URLs, and public chat role flags such as owner, moderator, member, or verified status
- Live stream IDs, video IDs, live chat IDs, channel IDs, stream titles, and other information needed to connect to and process the live chat
- OAuth access tokens and refresh tokens required for authentication

RCommentHub does not request permission to upload videos, modify channel data, post chat messages, or manage your YouTube account.

## How the Information Is Used

RCommentHub uses the information above only to provide user-facing live streaming support features, including:

- Retrieving YouTube Live chat
- Displaying comments in the RCommentHub user interface
- Showing overlays for streaming software such as OBS
- Reading comments aloud with local text-to-speech
- Filtering, searching, and managing comments and chat authors
- Saving local session logs for the user's own review
- Sending matching comment data to RRoulette through a local `127.0.0.1` connection when the user enables RRoulette integration
- Recording local diagnostic information such as API usage, route status, and connection errors

## Local Storage

RCommentHub is a desktop application. Data is stored on the user's local PC.

- OAuth tokens are saved locally in a `token.json` file in the RCommentHub runtime folder.
- User settings are saved locally in `rcommenthub_settings.json`.
- API keys, if used, are stored locally in the settings file using Windows DPAPI encryption.
- Live chat session logs may be saved locally under `logs/sessions/`, including `session_meta.json`, `comments.jsonl`, and optional user snapshots.
- Local diagnostic logs may be saved under `logs/`.
- User-provided OAuth client configuration files such as `client_secrets.json` remain local.

The developer does not operate a server that receives or stores RCommentHub OAuth tokens, YouTube Live chat messages, chat author data, or local session logs.

## Data Sharing

RCommentHub does not sell user data. RCommentHub does not provide user data to third parties for advertising, analytics, data brokerage, credit evaluation, or surveillance.

RCommentHub communicates with Google and YouTube APIs as necessary to provide YouTube Live chat features. If the user enables optional integrations, RCommentHub may also communicate with local tools such as RRoulette on `127.0.0.1`. Optional Twitch-related features, if configured by the user, communicate with Twitch APIs and store Twitch tokens locally.

## Google API Services User Data Policy

RCommentHub's use and transfer of information received from Google APIs adheres to the [Google API Services User Data Policy](https://developers.google.com/terms/api-services-user-data-policy), including the Limited Use requirements.

Information received from Google APIs is used only to provide or improve user-facing features that are visible in RCommentHub. It is not transferred except as needed to provide those user-facing features with the user's configuration and consent, for security purposes, to comply with applicable law, or as otherwise allowed by the Google API Services User Data Policy.

## Revoking Access

You can revoke RCommentHub's access to your Google Account at any time from [Google Account Permissions](https://myaccount.google.com/permissions).

You can also remove local RCommentHub data by deleting the local `token.json`, settings file, and log folders from the RCommentHub runtime folder.

## Security

Because RCommentHub stores data locally, you are responsible for protecting access to your PC and the RCommentHub runtime folder. Do not share local token, settings, log, or OAuth client configuration files with others unless you understand what they contain.

## Contact

For questions, privacy requests, or issue reports, please use GitHub Issues:

https://github.com/rrryutaro/RYouTubeLiveTools/issues

## Changes

This policy may be updated when RYouTubeLiveTools changes how it accesses, uses, stores, or shares data.
