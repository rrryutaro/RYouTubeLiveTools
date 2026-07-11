"""
update_flow_mixin.py — 自動アップデートの UI フロー Mixin（P1）

仕様: 自動アップデート機能 設計仕様

責務（P1: チェック＋通知＋リリースページを開く）:
  - ManagePanel の [更新を確認] 手動チェック処理（ダイアログ制御）
  - 起動時の非同期チェック（ウィンドウ表示後・非ブロッキング）
  - 更新あり時の通知（手動=モーダル / 起動時=バッジ＋ステータスの控えめ通知）
  - 「このバージョンをスキップ」の記録

ダウンロード〜差し替え〜再起動は後続 P2/P3。本 Mixin は
`update_worker.UpdateCheckWorker`（QThread）でチェックを非同期化し、
結果に応じて UI（ManagePanel）とダイアログを更新する。

使用側:
    class MainWindow(..., UpdateFlowMixin, ..., QMainWindow):
        self._init_manage_panel(central)   # self._manage_panel を生成
        ...
        self._init_update_flow()           # __init__ 末尾で1回呼ぶ

self._manage_panel / self._settings / self._save_config() に依存する。
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox, QProgressDialog, QApplication

import updater


class UpdateFlowMixin:
    """更新チェック〜適用の UI フローを担う Mixin。MainWindow の self.* 前提。"""

    # ------------------------------------------------------------------
    #  初期化
    # ------------------------------------------------------------------

    def _init_update_flow(self):
        """更新フローの初期状態を整える（__init__ 末尾で1回呼ぶ）。"""
        self._update_worker = None
        self._update_dl_worker = None
        self._update_progress = None
        # frozen 版では前回更新の残骸（.old / 未適用 new / 一時領域）を掃除する。
        # 新版が正常起動したこの時点で行う（設計 §6.4/§7）。
        if updater.detect_distribution() != "source":
            try:
                updater.cleanup_leftovers(updater.exe_dir())
            except Exception as e:
                print(f"[update] 起動時クリーンアップ失敗（無視）: {e}")
        # source（Python 実行）/ 開発ビルドは更新チェック対象外 → ボタン無効化。
        # （検証用の環境変数が立っている場合は有効のまま。updater 参照）
        if not updater.update_checks_enabled():
            self._manage_panel.update_set_disabled(
                "開発版のため更新確認は行いません"
            )
        import sys as _sys
        # PyInstaller 実行時環境変数の継承診断（更新後の再起動で古い展開先を
        # 掴む不具合の追跡用）。正常な起動ではこれらは付かない。
        _pyi_env = sorted(
            k for k in os.environ
            if k.startswith("_MEIPASS") or k.startswith("_PYI") or k.startswith("_MEI")
        )
        self._update_log(
            f"init: dist={updater.detect_distribution()} "
            f"current=v{updater.current_version()} "
            f"exe_dir={updater.exe_dir()} "
            f"meipass={getattr(_sys, '_MEIPASS', None)} "
            f"inherited_pyi_env={_pyi_env}"
        )

    # ------------------------------------------------------------------
    #  診断ログ（frozen はコンソールが無いためファイルに出す）
    # ------------------------------------------------------------------

    def _update_log(self, msg: str):
        """更新フローの診断ログを exe_dir\\update_flow.log に追記する。"""
        try:
            import datetime
            stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            path = os.path.join(updater.exe_dir(), "update_flow.log")
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"[{stamp}] {msg}\n")
        except Exception:
            pass

    @staticmethod
    def _plain_from_markdown(md: str, limit: int = 400) -> str:
        """リリースノート(Markdown)を、ダイアログ表示用のプレーン文へ簡易変換する。"""
        import re
        out = []
        for ln in (md or "").splitlines():
            s = ln.rstrip()
            s = re.sub(r"^\s*#{1,6}\s*", "", s)          # 見出し
            s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)        # 太字
            s = re.sub(r"__(.+?)__", r"\1", s)
            s = re.sub(r"`(.+?)`", r"\1", s)              # コード
            s = re.sub(r"^\s*[-*+]\s+", "・", s)          # 箇条書き
            out.append(s)
        text = "\n".join(out).strip()
        text = re.sub(r"\n{3,}", "\n\n", text)            # 連続空行を圧縮
        if len(text) > limit:
            text = text[:limit].rstrip() + "…"
        return text

    # ------------------------------------------------------------------
    #  手動チェック（ManagePanel の [更新を確認]）
    # ------------------------------------------------------------------

    def _on_update_check_requested(self):
        """[更新を確認] クリック → 手動チェック開始。"""
        self._start_update_check(manual=True)

    # ------------------------------------------------------------------
    #  起動時チェック（非ブロッキング）
    # ------------------------------------------------------------------

    def _maybe_check_update_on_startup(self):
        """起動時の非同期チェック。ウィンドウ表示後に呼ぶ（仕様 §9）。

        - update_check_on_startup が OFF → 何もしない
        - source / 開発ビルド → 何もしない
        - それ以外 → バックグラウンドでチェック（manual=False）
        """
        if not getattr(self._settings, "update_check_on_startup", True):
            return
        if not updater.update_checks_enabled():
            return
        self._start_update_check(manual=False)

    # ------------------------------------------------------------------
    #  ワーカー起動・後始末
    # ------------------------------------------------------------------

    def _start_update_check(self, manual: bool):
        """UpdateCheckWorker を起動する。多重起動はガードする。"""
        w = getattr(self, "_update_worker", None)
        if w is not None and w.isRunning():
            return  # 既にチェック中
        if manual:
            self._manage_panel.update_set_checking()

        from update_worker import UpdateCheckWorker
        worker = UpdateCheckWorker(timeout=10, manual=manual, parent=self)
        # manual をクロージャで束ねる（結果受信時に _update_worker が
        # 差し替わっていても正しい値を使えるようにする）。
        worker.check_finished.connect(
            lambda rel, m=manual: self._on_update_check_finished(rel, m)
        )
        worker.check_failed.connect(
            lambda msg, m=manual: self._on_update_check_failed(msg, m)
        )
        worker.finished.connect(lambda wk=worker: self._on_update_worker_done(wk))
        self._update_worker = worker
        worker.start()

    def _on_update_worker_done(self, worker):
        """ワーカー終了時の後始末（GC 保護参照の解放）。"""
        try:
            worker.deleteLater()
        except Exception:
            pass
        if getattr(self, "_update_worker", None) is worker:
            self._update_worker = None

    # ------------------------------------------------------------------
    #  結果ハンドラ
    # ------------------------------------------------------------------

    def _on_update_check_finished(self, release, manual: bool):
        """チェック成功。release=None は最新（または対象外）。"""
        if release is None:
            if manual:
                self._manage_panel.update_set_latest()
                QMessageBox.information(
                    self, "RRoulette",
                    "お使いのバージョンが最新です。",
                )
            # 起動時は無表示（仕様 §9）
            return

        version = release.version
        # バッジ／ステータスは手動・起動時いずれも更新する。
        self._manage_panel.update_set_available(version)

        skipped = getattr(self._settings, "update_skipped_version", None)
        if not manual and skipped == version:
            # 起動時 & スキップ済み → モーダルを出さずバッジのみ。
            self._update_log(f"startup: v{version} は skip 済みのため通知しない")
            return
        # 手動・起動時（未スキップ）いずれもモーダルで案内する（ユーザー要望）。
        self._show_update_available_dialog(release)

    def _on_update_check_failed(self, msg: str, manual: bool):
        """チェック失敗。手動時のみ通知、起動時は沈黙（ログのみ）。"""
        if manual:
            self._manage_panel.update_set_error()
            QMessageBox.warning(
                self, "RRoulette",
                f"更新の確認に失敗しました。\nネットワーク接続を確認してください。\n\n{msg}",
            )
        else:
            print(f"[update] 起動時チェック失敗（無視）: {msg}")

    # ------------------------------------------------------------------
    #  ダイアログ（更新あり）
    # ------------------------------------------------------------------

    def _compute_update_plan(self, release):
        """配布形態＋manifest から UpdatePlan を求める。

        folder 版のみ manifest（リモート=資産 / 現地）を参照する。manifest 取得は
        数十〜数百KB で、手動チェックの「更新あり」ダイアログ直前の一瞬のみ同期取得する。
        """
        dist = updater.detect_distribution()
        remote_manifest = None
        local_manifest = None
        if dist == "folder":
            ma = release.asset(updater.MANIFEST_NAME)
            if ma is not None and ma.url:
                remote_manifest = updater.fetch_remote_manifest(ma.url, timeout=10)
            local_manifest = updater.load_local_manifest(updater.exe_dir())
        plan = updater.plan_update(
            dist, release,
            remote_manifest=remote_manifest, local_manifest=local_manifest,
        )
        # 診断: 実機での判定不一致（例: folder 誤判定）を追跡できるよう記録する。
        lf = (local_manifest or {}).get("runtime_fingerprint", "")
        rf = (remote_manifest or {}).get("runtime_fingerprint", "")
        self._update_log(
            f"plan: dist={dist} mode={plan.mode} can_auto={plan.can_auto} "
            f"reason='{plan.reason}' local_fp={lf[:12]} remote_fp={rf[:12]} "
            f"assets={sorted(release.assets)}"
        )
        return plan

    def _show_update_available_dialog(self, release):
        """更新あり時のモーダル案内。

        - 自動更新可能（onefile / folder 依存不変）: 「更新する」→ DL→適用。
        - 自動更新不可（依存変化 / source 検証 等）: 「リリースページを開く」誘導。
        いずれも「このバージョンをスキップ」「後で」を用意する（設計 §8）。
        """
        version = release.version
        plan = self._compute_update_plan(release)

        excerpt = self._plain_from_markdown(release.body, limit=400)

        text = f"新しいバージョン v{version} があります。\n\n"
        if excerpt:
            text += f"【変更概要】\n{excerpt}\n\n"
        if plan.can_auto:
            text += "今すぐ更新しますか？（ダウンロード後にアプリを再起動して適用します）"
        else:
            reason = plan.reason or "この環境では自動更新に対応していません"
            text += f"（{reason}）\nリリースページを開いて手動で更新できます。"

        box = QMessageBox(self)
        box.setWindowTitle("RRoulette アップデート")
        box.setIcon(QMessageBox.Icon.Information)
        box.setText(text)
        if plan.can_auto:
            primary = box.addButton("更新する", QMessageBox.ButtonRole.AcceptRole)
        else:
            primary = box.addButton("リリースページを開く",
                                     QMessageBox.ButtonRole.AcceptRole)
        skip_btn = box.addButton("このバージョンをスキップ",
                                 QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("後で", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(primary)
        box.exec()

        clicked = box.clickedButton()
        if clicked is primary:
            if plan.can_auto:
                self._begin_update_download(release, plan)
            else:
                self._open_release_page(release)
        elif clicked is skip_btn:
            self._settings.update_skipped_version = version
            self._save_config()
            self._manage_panel.update_set_skipped(version)

    # ------------------------------------------------------------------
    #  ダウンロード＋適用（P2/P3）
    # ------------------------------------------------------------------

    def _begin_update_download(self, release, plan):
        """書き込み権限を確認し、ダウンロード（進捗ダイアログ）を開始する。"""
        install_dir = updater.exe_dir()
        if not updater.has_write_permission(install_dir):
            box = QMessageBox(self)
            box.setWindowTitle("RRoulette アップデート")
            box.setIcon(QMessageBox.Icon.Warning)
            box.setText(
                "インストール先フォルダに書き込めないため自動更新できません。\n"
                f"{install_dir}\n\n"
                "別の場所（例: ダウンロードフォルダ）に配置するか、"
                "リリースページから手動で更新してください。"
            )
            open_btn = box.addButton("リリースページを開く",
                                     QMessageBox.ButtonRole.AcceptRole)
            box.addButton("後で", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() is open_btn:
                self._open_release_page(release)
            return

        dl = getattr(self, "_update_dl_worker", None)
        if dl is not None and dl.isRunning():
            return  # 既にダウンロード中

        # 進捗ダイアログ（キャンセル可）
        total_hint = plan.asset_size or 0
        progress = QProgressDialog("更新をダウンロードしています…", "キャンセル",
                                   0, total_hint if total_hint else 0, self)
        progress.setWindowTitle("RRoulette アップデート")
        progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.setValue(0)
        self._update_progress = progress

        from update_worker import UpdateDownloadWorker
        worker = UpdateDownloadWorker(plan, release, install_dir, parent=self)
        worker.progress.connect(self._on_update_download_progress)
        worker.finished_ok.connect(
            lambda staged, rel=release: self._on_update_download_finished(staged, rel)
        )
        worker.failed.connect(self._on_update_download_failed)
        worker.cancelled.connect(self._on_update_download_cancelled)
        worker.finished.connect(lambda wk=worker: self._on_dl_worker_done(wk))
        progress.canceled.connect(worker.cancel)
        self._update_dl_worker = worker
        self._update_log(
            f"download: start mode={plan.mode} asset={plan.asset_name} "
            f"size={plan.asset_size} install_dir={install_dir}"
        )
        worker.start()
        progress.show()

    def _on_update_download_progress(self, downloaded, total):
        p = getattr(self, "_update_progress", None)
        if p is None:
            return
        if total:
            if p.maximum() != total:
                p.setMaximum(int(total))
            p.setValue(int(downloaded))
            mb = downloaded / (1024 * 1024)
            tmb = total / (1024 * 1024)
            p.setLabelText(f"更新をダウンロードしています… {mb:.1f} / {tmb:.1f} MB")
        else:
            # 合計不明: ビジー表示
            p.setMaximum(0)
            mb = downloaded / (1024 * 1024)
            p.setLabelText(f"更新をダウンロードしています… {mb:.1f} MB")

    def _close_update_progress(self):
        p = getattr(self, "_update_progress", None)
        if p is not None:
            p.close()
            self._update_progress = None

    def _on_update_download_finished(self, staged, release):
        """ダウンロード完了 → 適用前確認 → ヘルパー起動して再起動。"""
        self._close_update_progress()
        self._update_log(f"download: finished staged={staged}")
        box = QMessageBox(self)
        box.setWindowTitle("RRoulette アップデート")
        box.setIcon(QMessageBox.Icon.Question)
        box.setText(
            f"更新の準備ができました（v{release.version}）。\n"
            "アプリを再起動して適用します。よろしいですか？"
        )
        apply_btn = box.addButton("今すぐ再起動して更新",
                                   QMessageBox.ButtonRole.AcceptRole)
        box.addButton("キャンセル", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(apply_btn)
        box.exec()

        if box.clickedButton() is apply_btn:
            self._apply_staged_update()
        else:
            # キャンセル: ステージング済み素材を破棄
            install_dir = updater.exe_dir()
            for name in (updater._NEW_EXE_NAME, updater._NEW_MANIFEST_NAME):
                updater._safe_remove(os.path.join(install_dir, name))

    def _apply_staged_update(self):
        """差し替えヘルパー（bat）を起動し、アプリを終了する。"""
        install_dir = updater.exe_dir()
        try:
            bat = updater.write_helper_and_launch(os.getpid(), install_dir)
            self._update_log(f"apply: helper launched pid={os.getpid()} bat={bat}")
        except Exception as e:
            self._update_log(f"apply: helper launch FAILED {type(e).__name__}: {e}")
            QMessageBox.warning(
                self, "RRoulette",
                f"更新の適用に失敗しました。\n{type(e).__name__}: {e}",
            )
            return
        # ヘルパーが PID 終了を待って差し替え→再起動する。ここでアプリを終了する。
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _on_update_download_failed(self, msg):
        self._close_update_progress()
        QMessageBox.warning(
            self, "RRoulette",
            f"更新のダウンロードに失敗しました。\n{msg}",
        )

    def _on_update_download_cancelled(self):
        self._close_update_progress()

    def _on_dl_worker_done(self, worker):
        try:
            worker.deleteLater()
        except Exception:
            pass
        if getattr(self, "_update_dl_worker", None) is worker:
            self._update_dl_worker = None

    def _open_release_page(self, release):
        """GitHub のリリースページ（特定タグ）をブラウザで開く。"""
        import webbrowser
        from constants import GITHUB_OWNER, GITHUB_REPO
        tag = release.tag or f"{updater.RELEASE_TAG_PREFIX}{release.version}"
        url = (
            f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}"
            f"/releases/tag/{tag}"
        )
        self._open_url_in_browser(url)

    def _open_url_in_browser(self, url: str):
        """URL をブラウザで開く（失敗時は URL を提示）。"""
        import webbrowser
        try:
            webbrowser.open(url)
        except Exception as e:
            print(f"[update] URL を開けません: {e}")
            QMessageBox.warning(self, "RRoulette", f"ページを開けませんでした。\n{url}")

    def _on_open_releases_page(self):
        """v0.6.6: 「リリースページ」ボタン → リリース一覧を開く。"""
        from constants import RELEASES_URL
        self._open_url_in_browser(RELEASES_URL)

    def _on_open_manual_page(self):
        """v0.6.6: 「マニュアル」ボタン → 使い方ページを開く。"""
        from constants import MANUAL_URL
        self._open_url_in_browser(MANUAL_URL)
