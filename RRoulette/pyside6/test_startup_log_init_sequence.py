"""
i407 回帰テスト: pattern_id ベースでの起動シーケンス確認

## テスト設計の根拠

i406 までの問題:
- ログが pattern 表示名に依存 → リネームや設定不一致でログが消える
- 全パターン=OFF のとき、current_pattern と保存ログの名前が違うと空になる

i407 の修正:
- ログは pattern_id（UUID）で保存・フィルタ
- リネームしても UUID は変わらないため、ログが消えない
- 旧フォーマット（pattern_id なし）は安全側で除外

## 実機起動シーケンスの再現

1. _create_roulette → wheel.set_log_visible / set_log_all_patterns
2. load_log (i407: pattern_id ベース。旧形式エントリは除外)
3. [i405/i407 fix] set_current_pattern(name, pid)
4. _restore_extra_roulettes → set_log_visible / set_log_on_top / set_log_all_patterns
5. _sync_settings_to_active → set_current_pattern(name, pid)

実行方法:
  cd RRoulette/pyside6
  set QT_QPA_PLATFORM=offscreen && python test_startup_log_init_sequence.py
"""

import json
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer

_app = QApplication.instance() or QApplication(sys.argv)

from wheel_widget import WheelWidget   # noqa: E402
from roulette_panel import RoulettePanel  # noqa: E402
from bridge import DesignSettings  # noqa: E402

try:
    from RRoulette.sound_manager import SoundManager as _SM
except ImportError:
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
        from sound_manager import SoundManager as _SM
    except ImportError:
        _SM = None


# ---------------------------------------------------------------------------
#  ヘルパー
# ---------------------------------------------------------------------------

PID_MAIN = "pid-main-0001-0001-000000000001"
PID_OTHER = "pid-other-0002-0002-000000000002"

PATTERN_NAME = "テストパターン"
OTHER_PATTERN = "サブパターン"

LOG_ENTRIES_V2 = [
    {"ts": "2026-01-01 00:00:01", "text": "当選A", "pattern_id": PID_MAIN},
    {"ts": "2026-01-01 00:00:02", "text": "当選B", "pattern_id": PID_MAIN},
    {"ts": "2026-01-01 00:00:03", "text": "当選C", "pattern_id": PID_MAIN},
    {"ts": "2026-01-01 00:00:04", "text": "別P当選", "pattern_id": PID_OTHER},
]

LOG_ENTRIES_OLD = [
    {"ts": "2026-01-01 00:00:01", "text": "当選A", "pattern": PATTERN_NAME},
    {"ts": "2026-01-01 00:00:02", "text": "当選B", "pattern": PATTERN_NAME},
]


def _make_log_file(entries: list[dict]) -> str:
    """テスト用一時ログ JSON を作成してパスを返す。"""
    f = tempfile.NamedTemporaryFile(
        suffix=".json", mode="w", encoding="utf-8", delete=False
    )
    json.dump(entries, f, ensure_ascii=False)
    f.close()
    return f.name


def _make_sound_manager():
    if _SM is None:
        return None
    try:
        return _SM()
    except Exception:
        return None


def _make_roulette_panel(parent=None) -> RoulettePanel:
    design = DesignSettings()
    sm = _make_sound_manager()
    return RoulettePanel(design, sm, roulette_id="default", parent=parent)


def _process_events():
    _app.processEvents()


# ---------------------------------------------------------------------------
#  テストA: 起動直後シーケンス（log_all_patterns=OFF、v2 ログ）
# ---------------------------------------------------------------------------

def test_a_startup_sequence_off():
    """起動直後の呼び出し順を再現し、log_all_patterns=OFF で現在パターンが見えること。

    i407: ログは pattern_id で保存・フィルタ。set_current_pattern に UUID を渡せば
    起動直後でも正しく表示される。
    """
    path = _make_log_file(LOG_ENTRIES_V2)
    try:
        w = WheelWidget()

        # Phase 1: _create_roulette
        w.set_log_visible(True)
        w.set_log_all_patterns(False)

        # Phase 2: load_log (i407: pattern_id ベース)
        w.load_log(path)

        # Phase 3: set_current_pattern with UUID (i405/i407 fix)
        w.set_current_pattern(PATTERN_NAME, PID_MAIN)

        # Phase 4: _restore_extra_roulettes の "default" 処理
        w.set_log_visible(True)
        w.set_log_on_top(False)
        w.set_log_all_patterns(False)

        # Phase 5: _sync_settings_to_active 相当
        w.set_current_pattern(PATTERN_NAME, PID_MAIN)

        entries = w.get_log_entries()
        assert len(entries) == 3, (
            f"PID_MAIN のエントリは 3 件のはず。実際: {len(entries)} 件。"
            f"0 件なら current_pattern_id が未設定のまま。"
        )
    finally:
        os.unlink(path)


# ---------------------------------------------------------------------------
#  テストB: 起動直後シーケンス（log_all_patterns=ON）
# ---------------------------------------------------------------------------

def test_b_startup_sequence_on():
    """同条件で log_all_patterns=True → 全パターン（4件）が見えること。"""
    path = _make_log_file(LOG_ENTRIES_V2)
    try:
        w = WheelWidget()
        w.set_log_visible(True)
        w.set_log_all_patterns(False)
        w.load_log(path)
        w.set_current_pattern(PATTERN_NAME, PID_MAIN)
        w.set_log_visible(True)
        w.set_log_on_top(False)
        w.set_log_all_patterns(False)
        w.set_current_pattern(PATTERN_NAME, PID_MAIN)

        w.set_log_all_patterns(True)   # ユーザーが ON にした相当

        entries = w.get_log_entries()
        assert len(entries) == 4, (
            f"全パターンで 4 件のはず。実際: {len(entries)} 件。"
        )
    finally:
        os.unlink(path)


# ---------------------------------------------------------------------------
#  テストC: ON→OFF 即時切替
# ---------------------------------------------------------------------------

def test_c_toggle_on_to_off():
    """起動後に log_all_patterns を True→False へ変更すると現在パターン件数に即時切替すること。"""
    path = _make_log_file(LOG_ENTRIES_V2)
    try:
        w = WheelWidget()
        w.set_log_visible(True)
        w.set_log_all_patterns(False)
        w.load_log(path)
        w.set_current_pattern(PATTERN_NAME, PID_MAIN)
        w.set_log_visible(True)
        w.set_log_on_top(False)
        w.set_log_all_patterns(False)
        w.set_current_pattern(PATTERN_NAME, PID_MAIN)

        w.set_log_all_patterns(True)
        assert len(w.get_log_entries()) == 4, "ON で 4 件見えること"

        w.set_log_all_patterns(False)
        entries = w.get_log_entries()
        assert len(entries) == 3, (
            f"OFF に戻したら PID_MAIN の 3 件のはず。実際: {len(entries)} 件。"
        )
    finally:
        os.unlink(path)


# ---------------------------------------------------------------------------
#  テストD: 旧フォーマット（pattern_id なし）のログは除外される
# ---------------------------------------------------------------------------

def test_d_old_format_log_discarded():
    """i407: 旧フォーマット（pattern_id なし）のログは load 時に除外される。

    起動直後に旧フォーマットのログを読んでも、ログが何も表示されないことを確認する。
    これは「安全側」の動作: 旧データよりクリーンスタートを優先する。
    """
    path = _make_log_file(LOG_ENTRIES_OLD)
    try:
        w = WheelWidget()
        w.set_log_visible(True)
        w.set_log_all_patterns(False)
        w.load_log(path)
        w.set_current_pattern(PATTERN_NAME, PID_MAIN)
        w.set_log_visible(True)
        w.set_log_on_top(False)
        w.set_log_all_patterns(False)
        w.set_current_pattern(PATTERN_NAME, PID_MAIN)

        entries = w.get_log_entries()
        assert entries == [], (
            f"旧フォーマットは除外されるはず。実際: {entries}"
        )

        # log_all_patterns=True でも除外されること
        w.set_log_all_patterns(True)
        entries_all = w.get_log_entries()
        assert entries_all == [], (
            f"全パターン表示でも旧フォーマットは除外されるはず。実際: {entries_all}"
        )
    finally:
        os.unlink(path)


# ---------------------------------------------------------------------------
#  テストE: RoulettePanel 経由の LogOverlay (_log_on_top=True パス)
# ---------------------------------------------------------------------------

def test_e_log_overlay_on_top_path():
    """log_on_top=True のとき _LogOverlay 経由でログが表示されること。"""
    path = _make_log_file(LOG_ENTRIES_V2)
    try:
        panel = _make_roulette_panel()
        w = panel.wheel

        w.set_log_visible(True)
        w.set_log_all_patterns(False)
        w.load_log(path)
        w.set_current_pattern(PATTERN_NAME, PID_MAIN)
        w.set_log_visible(True)
        w.set_log_on_top(True)
        w.set_log_all_patterns(False)
        w.set_current_pattern(PATTERN_NAME, PID_MAIN)

        entries = w.get_log_entries()
        assert len(entries) == 3, (
            f"log_on_top=True でも get_log_entries は 3 件のはず。実際: {len(entries)}"
        )

        overlay_entries = panel._log_overlay._entries
        assert len(overlay_entries) == 3, (
            f"_LogOverlay._entries は 3 件のはず。実際: {len(overlay_entries)}。"
        )
    finally:
        os.unlink(path)


# ---------------------------------------------------------------------------
#  テストF: load_log 後の _log_overlay 状態（log_on_top=False パス）
# ---------------------------------------------------------------------------

def test_f_log_overlay_state_after_load_log():
    """load_log 後、_LogOverlay の状態を確認する。

    load_log は log_changed を emit しないため、_LogOverlay は更新されない。
    set_current_pattern を呼んで初めて log_changed が emit される。
    """
    path = _make_log_file(LOG_ENTRIES_V2)
    try:
        panel = _make_roulette_panel()
        w = panel.wheel
        w.set_log_visible(True)
        w.set_log_on_top(True)
        w.set_log_all_patterns(False)

        w.load_log(path)
        overlay_after_load = list(panel._log_overlay._entries)

        w.set_current_pattern(PATTERN_NAME, PID_MAIN)
        overlay_after_set = list(panel._log_overlay._entries)

        assert overlay_after_load == [], (
            f"load_log のみでは LogOverlay は更新されないはず。"
            f"実際: {overlay_after_load}"
        )
        assert len(overlay_after_set) == 3, (
            f"set_current_pattern 後は LogOverlay に 3 件のはず。"
            f"実際: {len(overlay_after_set)}"
        )
    finally:
        os.unlink(path)


# ---------------------------------------------------------------------------
#  テストG: リネーム後もログが表示される（i407 の核心確認）
# ---------------------------------------------------------------------------

PID_DEFAULT = "pid-default-0001-0001-000000000001"
LOG_ENTRIES_RENAME = [
    {"ts": "2026-01-01 00:00:01", "text": "当選1", "pattern_id": PID_DEFAULT},
    {"ts": "2026-01-01 00:00:02", "text": "当選2", "pattern_id": PID_DEFAULT},
    {"ts": "2026-01-01 00:00:03", "text": "当選3", "pattern_id": PID_DEFAULT},
    {"ts": "2026-01-01 00:00:04", "text": "他当選", "pattern_id": PID_OTHER},
]


def test_g_rename_does_not_break_log():
    """i407: パターンリネーム後も UUID は変わらないためログが表示される。

    修正前(i406): rename_log_pattern() でエントリの pat 文字列を書き換えが必要
    修正後(i407): UUID が変わらないため書き換え不要。名前を変えて再設定するだけでよい。
    """
    path = _make_log_file(LOG_ENTRIES_RENAME)
    try:
        w = WheelWidget()
        w.set_log_visible(True)
        w.set_log_all_patterns(False)
        w.load_log(path)
        w.set_current_pattern("デフォルト", PID_DEFAULT)

        entries_before = w.get_log_entries()
        assert len(entries_before) == 3, (
            f"リネーム前は 3 件のはず。実際: {len(entries_before)}"
        )

        # --- パターンリネーム相当 ---
        # UUID は変わらない。表示名だけ変わる。
        w.set_current_pattern("デフォルトA-F", PID_DEFAULT)   # 同じ UUID

        entries_after = w.get_log_entries()
        assert len(entries_after) == 3, (
            f"リネーム後も UUID 一致で 3 件のはず。実際: {len(entries_after)}。"
            f"0 件なら UUID ベースのフィルタが機能していない。"
        )
    finally:
        os.unlink(path)


def test_g2_rename_does_not_show_other_pattern():
    """リネーム後、OFF でも他パターンが混入しないこと。"""
    path = _make_log_file(LOG_ENTRIES_RENAME)  # PID_DEFAULT x3, PID_OTHER x1
    try:
        w = WheelWidget()
        w.set_log_visible(True)
        w.set_log_all_patterns(False)
        w.load_log(path)
        w.set_current_pattern("デフォルトA-F", PID_DEFAULT)   # リネーム後

        entries = w.get_log_entries()
        assert len(entries) == 3, (
            f"OFF では PID_DEFAULT の 3 件のみのはず。実際: {len(entries)}"
        )
        texts = [t for _, t in entries]
        assert "他当選" not in texts, f"他パターンが混入: {texts}"
    finally:
        os.unlink(path)


# ---------------------------------------------------------------------------
#  テストH: multi で roulette 別フィルタが壊れない
# ---------------------------------------------------------------------------

def test_h_multi_roulette_filter():
    """multi 環境で roulette_id によるフィルタが機能すること。"""
    from win_history import WinHistory
    import tempfile

    f = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    f.close()
    try:
        wh = WinHistory(f.name)
        wh.record("当選A", PID_DEFAULT, roulette_id="r1", pattern_name="パターン1")
        wh.record("当選B", PID_DEFAULT, roulette_id="r2", pattern_name="パターン1")
        wh.record("当選C", PID_OTHER,   roulette_id="r1", pattern_name="パターン2")

        counts_r1 = wh.count_by_item(PID_DEFAULT, roulette_id="r1")
        assert counts_r1 == {"当選A": 1}, f"r1 PID_DEFAULT: {counts_r1}"

        counts_r2 = wh.count_by_item(PID_DEFAULT, roulette_id="r2")
        assert counts_r2 == {"当選B": 1}, f"r2 PID_DEFAULT: {counts_r2}"

        counts_all = wh.count_by_item(PID_DEFAULT, roulette_id=None)
        assert counts_all == {"当選A": 1, "当選B": 1}, f"全roulette PID_DEFAULT: {counts_all}"
    finally:
        os.unlink(f.name)


# ---------------------------------------------------------------------------
#  テストI: export/import が pattern_id 基準で成立する
# ---------------------------------------------------------------------------

def test_i_export_import_pattern_id():
    """export / import が pattern_id 基準で成立すること。"""
    from win_history import WinHistory
    import tempfile

    f_save = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    f_save.close()
    f_export = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    f_export.close()

    try:
        wh = WinHistory(f_save.name)
        wh.record("当選A", PID_DEFAULT, roulette_id="r1")
        wh.record("当選B", PID_OTHER,   roulette_id="r1")
        wh.save()

        # PID_DEFAULT のみエクスポート
        wh.export_to_json(f_export.name, pattern_id=PID_DEFAULT, roulette_id=None)

        # 別のインスタンスでインポート
        wh2 = WinHistory(f_save.name)
        wh2.record("既存C", PID_DEFAULT, roulette_id="r1")
        added = wh2.import_from_json(f_export.name)
        assert added == 1, f"重複なし1件追加のはず: {added}"

        # 再インポートで重複なし
        added2 = wh2.import_from_json(f_export.name)
        assert added2 == 0, f"重複なし0件のはず: {added2}"
    finally:
        os.unlink(f_save.name)
        os.unlink(f_export.name)


# ---------------------------------------------------------------------------
#  テストJ: 旧フォーマットの win_history.json は load 時にクリアされる
# ---------------------------------------------------------------------------

def test_j_old_win_history_discarded_on_load():
    """i407: win_history.json の旧フォーマット（pattern_id なし）は load 時に除外される。"""
    from win_history import WinHistory
    import tempfile

    old_data = {
        "records": [
            {"id": "rid1", "text": "当選A", "ts": "2026-01-01 00:00:01",
             "pattern": "パターン1", "roulette_id": "default"},
            {"id": "rid2", "text": "当選B", "ts": "2026-01-01 00:00:02",
             "pattern": "パターン2", "roulette_id": "default"},
        ]
    }
    f = tempfile.NamedTemporaryFile(suffix=".json", mode="w",
                                    encoding="utf-8", delete=False)
    json.dump(old_data, f)
    f.close()
    try:
        wh = WinHistory(f.name)
        wh.load()
        assert wh.records == [], (
            f"旧フォーマットは load 時に除外されるはず。実際: {wh.records}"
        )
    finally:
        os.unlink(f.name)


# ---------------------------------------------------------------------------
#  メインランナー
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_a_startup_sequence_off,
        test_b_startup_sequence_on,
        test_c_toggle_on_to_off,
        test_d_old_format_log_discarded,
        test_e_log_overlay_on_top_path,
        test_f_log_overlay_state_after_load_log,
        test_g_rename_does_not_break_log,
        test_g2_rename_does_not_show_other_pattern,
        test_h_multi_roulette_filter,
        test_i_export_import_pattern_id,
        test_j_old_win_history_discarded_on_load,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS: {t.__name__}")
        except AssertionError as e:
            print(f"  FAIL: {t.__name__}: {e}")
            failed += 1
        except Exception as e:
            import traceback
            print(f"  ERROR: {t.__name__}: {e}")
            traceback.print_exc()
            failed += 1
    print()
    if failed == 0:
        print(f"All {len(tests)} tests passed.")
        sys.exit(0)
    else:
        print(f"{failed}/{len(tests)} tests FAILED.")
        sys.exit(1)
