"""
RCommentHub — TTS サービス
  - win32com.client (SAPI5 直接利用) による in-process 読み上げ
  - pywin32 が利用できない環境への fallback として PowerShell 方式を残すが非推奨
  - キュー + デーモンスレッドで UI をブロックしない
  - 将来的に別エンジンへ差し替えやすいよう TTSService クラスに抽象化
"""

import queue
import subprocess
import threading
import re


class TTSService:
    """テキスト読み上げサービス（PowerShell SAPI バックエンド）"""

    def __init__(self):
        self._enabled = False
        # キューのエントリは (text: str, item: Any) のタプル、または None（終了シグナル）
        self._queue: queue.Queue = queue.Queue()
        # TTS が読み上げ開始する直前に呼ばれるコールバック (item) -> None
        self._on_speak = None

        # 読み上げフィルタ設定
        self._read_normal    = True   # 通常コメント
        self._read_superchat = True   # Super Chat
        self._read_owner     = True   # 配信者
        self._read_moderator = True   # モデレーター
        self._read_member    = False  # メンバー（デフォルト OFF）

        # 音量（0〜100）
        self._volume         = 100

        # 投稿者名簡略化（ON のとき author_display_name_tts を使用）
        self._simplify_name  = True

        # 接続先名を先頭で読み上げる
        self._read_source_name = False

        # コメント間インターバル（秒、0 = なし）
        self._interval_sec: float = 0.0

        # 読み上げ速度（1〜10、SAPI の Rate に対応: デフォルト 0）
        self._speed: int = 0

        # ワーカースレッド起動
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    # ─── 設定 ───────────────────────────────────────────────────────────────

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool):
        self._enabled = value

    @property
    def volume(self) -> int:
        return self._volume

    @volume.setter
    def volume(self, value: int):
        self._volume = max(0, min(100, int(value)))

    @property
    def simplify_name(self) -> bool:
        return self._simplify_name

    @simplify_name.setter
    def simplify_name(self, value: bool):
        self._simplify_name = value

    @property
    def read_source_name(self) -> bool:
        return self._read_source_name

    @read_source_name.setter
    def read_source_name(self, value: bool):
        self._read_source_name = value

    @property
    def interval_sec(self) -> float:
        return self._interval_sec

    @interval_sec.setter
    def interval_sec(self, value: float):
        self._interval_sec = max(0.0, float(value))

    @property
    def speed(self) -> int:
        return self._speed

    @speed.setter
    def speed(self, value: int):
        # SAPI Rate: -10〜10、ここでは 0〜10 の正方向のみ
        self._speed = max(-10, min(10, int(value)))

    def set_on_speak(self, callback):
        """
        TTS が読み上げを開始する直前に呼ばれるコールバックを設定する。
        callback: (item) -> None  ※ item が None のものは呼ばれない
        Overlay と TTS の同期に使う。
        """
        self._on_speak = callback

    def set_filter(self, *,
                   normal: bool | None = None,
                   superchat: bool | None = None,
                   owner: bool | None = None,
                   moderator: bool | None = None,
                   member: bool | None = None):
        if normal    is not None: self._read_normal    = normal
        if superchat is not None: self._read_superchat = superchat
        if owner     is not None: self._read_owner     = owner
        if moderator is not None: self._read_moderator = moderator
        if member    is not None: self._read_member    = member

    # ─── コメント投入 ────────────────────────────────────────────────────────

    def should_read(self, item) -> bool:
        """フィルタ条件に一致するか判定する（実際には読まない）"""
        return self._enabled and self._should_read(item)

    def enqueue_comment(self, item) -> bool:
        """
        CommentItem を読み上げキューへ投入。
        フィルタ条件に合わなければ無視。
        読み上げ対象になった場合 True を返す。
        """
        if not self._enabled:
            return False

        if not self._should_read(item):
            return False

        text = self._format(item)
        if text:
            self._queue.put((text, item))
            return True
        return False

    def speak(self, text: str):
        """任意テキストを直接キューへ投入（item なし）"""
        if self._enabled and text:
            self._queue.put((text, None))

    def speak_item(self, item) -> None:
        """CommentItem を強制読み上げ（ON/OFF・フィルタを無視）"""
        text = self._format(item)
        if text:
            self._queue.put((text, item))

    def stop(self):
        """ワーカー終了（アプリ終了時に呼ぶ）"""
        self._queue.put(None)

    # ─── 内部ロジック ────────────────────────────────────────────────────────

    def _should_read(self, item) -> bool:
        kind = item.kind

        # 種別フィルタ
        if kind == "textMessageEvent":
            if not self._read_normal:
                return False
        elif kind == "superChatEvent":
            if not self._read_superchat:
                return False
        elif kind in ("superStickerEvent", "memberMilestoneChatEvent",
                      "membershipGiftingEvent", "giftMembershipReceivedEvent"):
            if not self._read_superchat:
                return False
        else:
            # 削除・BAN・投票等はデフォルトで読まない
            return False

        # 投稿者属性フィルタ
        if item.is_owner and not self._read_owner:
            return False
        if item.is_moderator and not self._read_moderator:
            return False
        if item.is_member and not self._read_member:
            # メンバーのみの場合は通常コメント判定で通るが追加でチェック
            # ※ is_member が True でも通常コメントとして read_normal で通る設計
            pass

        return True

    def _format(self, item) -> str:
        """読み上げ用テキストを整形"""
        if self._simplify_name:
            name = getattr(item, "author_display_name_tts", None) or item.author_name or "名無し"
        else:
            name = item.author_name or "名無し"
        body = item.body or ""

        # 接続先名プレフィックス
        source_prefix = ""
        if self._read_source_name:
            from constants import SOURCE_DEFAULT_NAMES
            sid   = getattr(item, "source_id",   "conn1")
            sname = getattr(item, "source_name", "") or SOURCE_DEFAULT_NAMES.get(sid, sid)
            if sname:
                source_prefix = f"{sname}、"

        # URL・記号を除去
        body = re.sub(r'https?://\S+', '', body)
        body = body.strip()

        kind = item.kind
        if kind == "superChatEvent":
            from constants import EVENT_TYPE_LABELS
            snippet = item.raw.get("snippet", {})
            amt = snippet.get("superChatDetails", {}).get("amountDisplayString", "")
            if amt:
                prefix = f"スーパーチャット {amt}、"
            else:
                prefix = "スーパーチャット、"
            core = f"{name}、{prefix}{body}" if body else f"{name}、{prefix}"
            return f"{source_prefix}{core}"
        elif kind == "superStickerEvent":
            snippet = item.raw.get("snippet", {})
            amt = snippet.get("superStickerDetails", {}).get("amountDisplayString", "")
            return f"{source_prefix}{name}、スーパーステッカー {amt}"
        elif kind == "memberMilestoneChatEvent":
            d = item.raw.get("snippet", {}).get("memberMilestoneChatDetails", {})
            month = d.get("memberMonth", "")
            core = f"{name}、{month}ヶ月メンバー継続" + (f"、{body}" if body else "")
            return f"{source_prefix}{core}"
        else:
            core = f"{name}、{body}" if body else name
            return f"{source_prefix}{core}"

    def _run(self):
        """ワーカースレッド: キューからテキストを取り出して読み上げ"""
        import time
        speaker = self._init_sapi5()

        while True:
            entry = self._queue.get()
            if entry is None:
                break
            text, item = entry
            # 読み上げ開始前にコールバック（Overlay 同期用）
            if item is not None and self._on_speak is not None:
                try:
                    self._on_speak(item)
                except Exception:
                    pass
            if speaker is not None:
                self._speak_sapi5(text, speaker)
            else:
                self._speak_powershell_fallback(text)
            if self._interval_sec > 0:
                time.sleep(self._interval_sec)

        if speaker is not None:
            try:
                import pythoncom
                pythoncom.CoUninitialize()
            except Exception:
                pass

    def _init_sapi5(self):
        """
        SAPI5 スピーカーを初期化して返す（ワーカースレッド内で呼ぶこと）。
        win32com が利用できない場合は None を返す。
        """
        try:
            import pythoncom
            pythoncom.CoInitialize()
            import win32com.client
            return win32com.client.Dispatch("SAPI.SpVoice")
        except Exception:
            return None

    def _speak_sapi5(self, text: str, speaker) -> None:
        """win32com 経由で SAPI5 読み上げ（in-process・ブロッキング）"""
        try:
            speaker.Volume = self._volume
            speaker.Rate   = self._speed
            speaker.Speak(text)
        except Exception:
            pass

    def _speak_powershell_fallback(self, text: str) -> None:
        """
        PowerShell 経由での読み上げ（非推奨・win32com が使えない場合の最終 fallback）。
        配布向けには使用しないこと。
        """
        safe = text.replace("'", "\\'")
        script = (
            "Add-Type -AssemblyName System.Speech; "
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            f"$s.Volume = {self._volume}; "
            f"$s.Rate = {self._speed}; "
            f"$s.Speak('{safe}')"
        )
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive",
                 "-WindowStyle", "Hidden", "-Command", script],
                timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except Exception:
            pass
