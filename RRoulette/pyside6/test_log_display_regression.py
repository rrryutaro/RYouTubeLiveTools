"""
i407 回帰テスト: pattern_id ベースのログ表示整合確認

WheelWidget の get_log_entries() が以下の条件で正しく動作することを保証する。
  1. _current_pattern_id="" (未設定) → [] (ガード)
  2. set_current_pattern(name, pid) 後、log_all_patterns=False → 現在パターンIDのみ
  3. load_log → set_current_pattern の順で呼んだ後 → 現在パターンが見える
     (i407: UUID ベースなのでリネーム後も一致する)
  4. log_all_patterns=True → 全パターンが返る
  5. i407: リネームしても UUID で一致するためログが維持される

実行方法:
  cd RRoulette/pyside6
  set QT_QPA_PLATFORM=offscreen && python test_log_display_regression.py
"""
import json
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication
_app = QApplication.instance() or QApplication(sys.argv)

from wheel_widget import WheelWidget  # noqa: E402


# ---------------------------------------------------------------------------
#  ヘルパー
# ---------------------------------------------------------------------------

PID1 = "pid-0001-0001-0001-000000000001"
PID2 = "pid-0002-0002-0002-000000000002"


def _make_log_file_v2(entries: list[dict]) -> str:
    """テスト用一時ログ JSON (v2: pattern_id フィールドあり) を作成してパスを返す。"""
    f = tempfile.NamedTemporaryFile(
        suffix=".json", mode="w", encoding="utf-8", delete=False
    )
    json.dump(entries, f, ensure_ascii=False)
    f.close()
    return f.name


def _make_log_file_old(entries: list[dict]) -> str:
    """テスト用旧フォーマット（pattern フィールドのみ）の一時ログ JSON を作成する。"""
    return _make_log_file_v2(entries)  # 中身が旧フォーマットなだけ


# ---------------------------------------------------------------------------
#  テスト関数
# ---------------------------------------------------------------------------

def test_no_pattern_id_returns_empty():
    """起動直後: _current_pattern_id 未設定なら get_log_entries は [] を返す。"""
    w = WheelWidget()
    w._log_entries = [("2026-01-01 00:00:00", "当選A", PID1)]
    result = w.get_log_entries()
    assert result == [], (
        f"パターンID未設定時は [] のはず (実際: {result}). "
        "i407 ガードが外れていないか確認すること"
    )


def test_with_pattern_id_returns_filtered():
    """set_current_pattern(name, pid) 後: 現在パターンIDのエントリのみ返る。"""
    w = WheelWidget()
    w._log_entries = [
        ("2026-01-01 00:00:01", "当選A", PID1),
        ("2026-01-01 00:00:02", "当選B", PID2),
    ]
    w.set_current_pattern("パターン1", PID1)
    entries = w.get_log_entries()
    assert len(entries) == 1, f"PID1 は1件のはず: {entries}"
    assert entries[0][1] == "当選A", f"テキスト不一致: {entries}"


def test_load_log_then_set_pattern_shows_entries():
    """load_log 後に set_current_pattern を呼ぶと現在パターンが見える。

    i407: ログは pattern_id で保存されているため、名前一致は不要。
    UUID が一致すれば表示される。
    """
    path = _make_log_file_v2([
        {"ts": "2026-01-01 00:00:01", "text": "当選A", "pattern_id": PID1},
        {"ts": "2026-01-01 00:00:02", "text": "当選B", "pattern_id": PID1},
        {"ts": "2026-01-01 00:00:03", "text": "当選C", "pattern_id": PID2},
    ])
    try:
        w = WheelWidget()
        w.load_log(path)
        w.set_current_pattern("パターン1", PID1)
        entries = w.get_log_entries()
        assert len(entries) == 2, (
            f"PID1 のエントリは2件のはず。実際: {entries}"
        )
    finally:
        os.unlink(path)


def test_log_all_patterns_returns_all():
    """log_all_patterns=True で全パターンが返る。"""
    path = _make_log_file_v2([
        {"ts": "2026-01-01 00:00:01", "text": "当選A", "pattern_id": PID1},
        {"ts": "2026-01-01 00:00:02", "text": "当選B", "pattern_id": PID2},
    ])
    try:
        w = WheelWidget()
        w.load_log(path)
        w.set_current_pattern("パターン1", PID1)
        w.set_log_all_patterns(True)
        entries = w.get_log_entries()
        assert len(entries) == 2, f"全パターンで2件のはず: {entries}"
    finally:
        os.unlink(path)


def test_empty_pattern_id_entries_excluded_in_all_mode():
    """i407: log_all_patterns=True でも pattern_id="" のエントリは除外される。"""
    w = WheelWidget()
    w._log_entries = [
        ("2026-01-01 00:00:01", "当選A", PID1),
        ("2026-01-01 00:00:02", "旧データ", ""),   # pattern_id 空 = 除外対象
    ]
    w.set_current_pattern("パターン1", PID1)
    w.set_log_all_patterns(True)
    entries = w.get_log_entries()
    assert len(entries) == 1, f"空IDエントリは除外されるはず: {entries}"


def test_old_format_log_discarded_on_load():
    """i407: 旧フォーマット（pattern_id なし）のログは load 時に除外される。"""
    path = _make_log_file_old([
        {"ts": "2026-01-01 00:00:01", "text": "当選A", "pattern": "パターン1"},
        {"ts": "2026-01-01 00:00:02", "text": "当選B", "pattern": "パターン1"},
    ])
    try:
        w = WheelWidget()
        w.load_log(path)
        w.set_current_pattern("パターン1", PID1)
        w.set_log_all_patterns(True)
        entries = w.get_log_entries()
        assert entries == [], (
            f"旧フォーマットエントリは除外されるはず: {entries}"
        )
    finally:
        os.unlink(path)


def test_rename_does_not_break_log():
    """i407: パターンリネーム後もログは UUID で一致するため表示される。

    旧方式（i406）では rename_log_pattern() でエントリの name を書き換えていたが、
    i407 以降は UUID が変わらないためリネームの影響を受けない。
    """
    path = _make_log_file_v2([
        {"ts": "2026-01-01 00:00:01", "text": "当選1", "pattern_id": PID1},
        {"ts": "2026-01-01 00:00:02", "text": "当選2", "pattern_id": PID1},
        {"ts": "2026-01-01 00:00:03", "text": "他当選", "pattern_id": PID2},
    ])
    try:
        w = WheelWidget()
        w.load_log(path)
        w.set_current_pattern("デフォルト", PID1)   # リネーム前の名前で設定

        entries_before = w.get_log_entries()
        assert len(entries_before) == 2, (
            f"リネーム前: PID1 の 2 件のはず。実際: {len(entries_before)}"
        )

        # --- パターンリネーム相当: 名前だけ変わる、UUID は同じ ---
        # rename_log_pattern は不要。名前変更後もUUIDで set_current_pattern すればよい
        w.set_current_pattern("デフォルトA-F", PID1)   # リネーム後の名前、同じ UUID

        entries_after = w.get_log_entries()
        assert len(entries_after) == 2, (
            f"リネーム後も UUID が同じなので 2 件のはず。実際: {len(entries_after)}。"
            f"UUID ベースでフィルタしていれば名前変更の影響は受けない。"
        )
    finally:
        os.unlink(path)


def test_add_log_entry_with_pattern_id():
    """add_log_entry で pattern_id を指定してエントリを追加できる。"""
    w = WheelWidget()
    w.set_current_pattern("パターン1", PID1)
    w.add_log_entry("当選A", PID1)
    w.add_log_entry("当選B", PID2)
    entries = w.get_log_entries()
    assert len(entries) == 1, f"PID1 のエントリは1件のはず: {entries}"
    assert entries[0][1] == "当選A"


def test_all_patterns_mode_shows_both():
    """log_all_patterns=True では異なるUUIDのエントリが全件返る。"""
    w = WheelWidget()
    w.set_current_pattern("パターン1", PID1)
    w.set_log_all_patterns(True)
    w.add_log_entry("当選A", PID1)
    w.add_log_entry("当選B", PID2)
    entries = w.get_log_entries()
    assert len(entries) == 2, f"全パターンで2件のはず: {entries}"


# ---------------------------------------------------------------------------
#  メインランナー
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_no_pattern_id_returns_empty,
        test_with_pattern_id_returns_filtered,
        test_load_log_then_set_pattern_shows_entries,
        test_log_all_patterns_returns_all,
        test_empty_pattern_id_entries_excluded_in_all_mode,
        test_old_format_log_discarded_on_load,
        test_rename_does_not_break_log,
        test_add_log_entry_with_pattern_id,
        test_all_patterns_mode_shows_both,
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
