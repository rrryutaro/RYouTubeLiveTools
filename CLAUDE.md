# Claude Code — プロジェクトノート

## シェル環境

- OS: Windows 11
- シェル: Bash（Git Bash）  
  Unix 系の構文は使えるが、**coreutils はインストールされていない**
- 次のコマンドは **使用不可**: `head`, `tail`, `cat`, `find`, `grep`, `sed`, `awk`, `echo`（リダイレクト用途）, `cat <<EOF`（heredoc）
- `gh`（GitHub CLI）は **PATH に通っていない**  
  GitHub API は `python -c "import urllib.request; ..."` を使うこと
- 必要に応じて `git credential fill` で GitHub トークンを取得できる

## コマンドの代替手段

| 使用不可 | 代替手段 |
|---|---|
| `head -n N file` | Read ツール、または `python -c "open(f).readlines()[:N]"` |
| `cat file` | Read ツール |
| `find . -name "*.py"` | Glob ツール |
| `grep pattern file` | Grep ツール |
| `cat <<'EOF' > file`（heredoc） | Write ツール |
| `echo text >> file` | Edit または Write ツール |
| `git commit -m "$(cat <<'EOF'...)"` | `git commit -m "message"`（インラインで直接記述し、heredoc は使わない） |
| `gh release create ...` | Python の `urllib` を使った GitHub REST API |

## 推奨方針

1. **まず専用ツールを優先して使うこと**: Read, Write, Edit, Glob, Grep  
   これらは高速で、シェルコマンドに依存しない
2. **システム操作は Python を使うこと**: ファイル入出力、API 呼び出し、パス確認など  
   シェルユーティリティが不足しているため、`python -c "..."` または `python -` を使う
3. **コミットメッセージはインラインで書くこと**: `-m "..."` を直接使い、heredoc（`cat <<'EOF'`）は使わない
4. GitHub 操作（リリース作成、アセット添付など）は、Python の `urllib.request` と `git credential fill` で取得したトークンを使うこと

## Git ポリシー

- ユーザーの明示的な指示なしに commit や push をしてはいけない
- push 前に、push 単位ごとに 1 commit へ squash すること
- 履歴を書き換える push では `--force` ではなく `--force-with-lease` を使うこと

## セッション開始時
- 以下のファイルの内容に従う
  `G:\マイドライブ\AI\Rules\RYouTubeLiveTools_00_固定運用ルール_2026-04-03.md`
- 各指示にて同名のパスが記載されている場合、同一タイムスタンプなら変更なしのためスキップする
- 指示内容にブランチ情報の記載が無い場合、現在のブランチについて私に提示して確認を行う
