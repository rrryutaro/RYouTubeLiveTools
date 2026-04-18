"""
i412 テスト: log import 時の pattern_id 再マップ

## テスト内容

テスト1: pid_remap を使うと source_pid が dest_pid に変換されてログに保存されること
テスト2: pid_remap 後のレコードが dest_pid で検索可能なこと
テスト3: source_pid のまま残らないこと（dest_pid に変換済み）
テスト4: 同一 source_pid で複数回 pattern import したとき最後の dest_pid にマップされること
テスト5: i411 の cross-roulette dedup が pid_remap 使用後も壊れていないこと
テスト6: pid_remap=None の場合は変換なしで従来通り動くこと（後方互換）

実行方法:
  cd RRoulette/pyside6
  set QT_QPA_PLATFORM=offscreen && python test_pid_remap.py
"""

import json
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from win_history import WinHistory  # noqa: E402

# ---------------------------------------------------------------------------
#  定数
# ---------------------------------------------------------------------------

# source 側の pattern_id（#1 ルーレット由来）
SRC_PID = "src-pid-i412-0001-000000000001"
# destination 側の pattern_id（#2 ルーレットで新規採番）
DST_PID = "dst-pid-i412-0002-000000000002"

RID1 = "roulette-i412-001"
RID2 = "roulette-i412-002"


# ---------------------------------------------------------------------------
#  テスト1: pid_remap により source_pid が dest_pid に変換される
# ---------------------------------------------------------------------------

def test_1_pid_remap_converts_source_to_dest():
    """pid_remap を使うと source_pid が dest_pid に変換されてログに保存されること。"""
    f_export = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    f_export.close()

    try:
        # #1 のログ（SRC_PID で記録）
        wh_src = WinHistory()
        wh_src.record("当選A", SRC_PID, roulette_id=RID1, pattern_name="パターン1")
        wh_src.record("当選B", SRC_PID, roulette_id=RID1, pattern_name="パターン1")
        wh_src.export_to_json(f_export.name, pattern_id=None, roulette_id=RID1)

        # #2 に import（SRC_PID → DST_PID に再マップ）
        wh_dst = WinHistory()
        added = wh_dst.import_from_json(
            f_export.name,
            target_roulette_id=RID2,
            pid_remap={SRC_PID: DST_PID},
        )

        assert added == 2, f"2件追加されるはず: {added}"

        # 保存されたレコードの pattern_id が DST_PID になっている
        for rec in wh_dst.records:
            assert rec["pattern_id"] == DST_PID, (
                f"保存レコードの pattern_id が DST_PID になるべき。"
                f"実際: {rec['pattern_id']}"
            )

    finally:
        os.unlink(f_export.name)


# ---------------------------------------------------------------------------
#  テスト2: pid_remap 後のレコードが dest_pid で検索可能
# ---------------------------------------------------------------------------

def test_2_imported_log_visible_via_dest_pid():
    """pid_remap 後のレコードが dest_pid / RID2 で count_by_item に反映されること。"""
    f_export = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    f_export.close()

    try:
        wh_src = WinHistory()
        wh_src.record("当選A", SRC_PID, roulette_id=RID1)
        wh_src.record("当選A", SRC_PID, roulette_id=RID1)
        wh_src.record("当選B", SRC_PID, roulette_id=RID1)
        wh_src.export_to_json(f_export.name, pattern_id=None, roulette_id=RID1)

        wh_dst = WinHistory()
        wh_dst.import_from_json(
            f_export.name,
            target_roulette_id=RID2,
            pid_remap={SRC_PID: DST_PID},
        )

        # DST_PID + RID2 で集計できる
        counts = wh_dst.count_by_item(DST_PID, roulette_id=RID2)
        assert counts == {"当選A": 2, "当選B": 1}, (
            f"DST_PID/RID2 で集計できるはず。実際: {counts}"
        )

        # SRC_PID では何も出ない（source_pid が残っていない）
        counts_src = wh_dst.count_by_item(SRC_PID, roulette_id=RID2)
        assert counts_src == {}, (
            f"SRC_PID では空になるはず（変換済み）。実際: {counts_src}"
        )

    finally:
        os.unlink(f_export.name)


# ---------------------------------------------------------------------------
#  テスト3: source_pid のまま残らないこと
# ---------------------------------------------------------------------------

def test_3_source_pid_not_stored():
    """pid_remap 後、保存レコードに SRC_PID が残らないこと。"""
    f_export = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    f_export.close()

    try:
        wh_src = WinHistory()
        wh_src.record("当選X", SRC_PID, roulette_id=RID1)
        wh_src.export_to_json(f_export.name, pattern_id=None, roulette_id=RID1)

        wh_dst = WinHistory()
        wh_dst.import_from_json(
            f_export.name,
            target_roulette_id=RID2,
            pid_remap={SRC_PID: DST_PID},
        )

        for rec in wh_dst.records:
            assert rec.get("pattern_id") != SRC_PID, (
                f"SRC_PID がそのまま保存されてはいけない。レコード: {rec}"
            )

    finally:
        os.unlink(f_export.name)


# ---------------------------------------------------------------------------
#  テスト4: 同一 source_pid で複数 import → 最後の dest_pid が使われる
# ---------------------------------------------------------------------------

def test_4_multiple_import_last_wins():
    """同一 source_pid で複数回 pattern import した場合、最後の dest_pid にマップされること。"""
    DST_PID_FIRST = "dst-pid-i412-first"
    DST_PID_LAST  = "dst-pid-i412-last"

    # 2回の pattern import を模擬: 最後に DST_PID_LAST が登録されたとする
    pid_map = {}
    # 1回目
    pid_map[SRC_PID] = DST_PID_FIRST
    # 2回目（上書き）
    pid_map[SRC_PID] = DST_PID_LAST

    assert pid_map[SRC_PID] == DST_PID_LAST, (
        "同一 source_pid の複数 import では最後の dest_pid が使われるべき"
    )

    # 実際に log import で確認
    f_export = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    f_export.close()

    try:
        wh_src = WinHistory()
        wh_src.record("当選Y", SRC_PID, roulette_id=RID1)
        wh_src.export_to_json(f_export.name, pattern_id=None, roulette_id=RID1)

        wh_dst = WinHistory()
        wh_dst.import_from_json(
            f_export.name,
            target_roulette_id=RID2,
            pid_remap=pid_map,
        )

        assert wh_dst.records[0]["pattern_id"] == DST_PID_LAST, (
            f"最後の dest_pid で保存されるべき。実際: {wh_dst.records[0]['pattern_id']}"
        )

    finally:
        os.unlink(f_export.name)


# ---------------------------------------------------------------------------
#  テスト5: i411 の cross-roulette dedup が pid_remap 使用後も壊れていないこと
# ---------------------------------------------------------------------------

def test_5_cross_roulette_dedup_with_pid_remap():
    """pid_remap を使っても cross-roulette import の dedup が正しく動くこと。"""
    f_export = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    f_export.close()

    try:
        # source: RID1 の3件
        wh_src = WinHistory()
        for i in range(3):
            wh_src.record(f"項目{i}", SRC_PID, roulette_id=RID1)
        wh_src.export_to_json(f_export.name, pattern_id=None, roulette_id=RID1)

        # destination: RID1 の同じレコードが既に存在（id 衝突の可能性）
        wh_dst = WinHistory()
        for i in range(3):
            wh_dst.record(f"項目{i}", SRC_PID, roulette_id=RID1)

        # RID2 へ pid_remap 付きで import → RID1 の既存レコードと id が衝突しても通るべき
        added = wh_dst.import_from_json(
            f_export.name,
            target_roulette_id=RID2,
            pid_remap={SRC_PID: DST_PID},
        )

        assert added == 3, (
            f"pid_remap 使用時も cross-roulette import で3件追加されるべき。実際: {added}"
        )

        # RID2 のレコードは DST_PID を持つ
        r2 = [r for r in wh_dst.records if r["roulette_id"] == RID2]
        assert len(r2) == 3
        for rec in r2:
            assert rec["pattern_id"] == DST_PID

        # RID1 は不変（3件のまま SRC_PID）
        r1 = [r for r in wh_dst.records if r["roulette_id"] == RID1]
        assert len(r1) == 3

    finally:
        os.unlink(f_export.name)


# ---------------------------------------------------------------------------
#  テスト6: pid_remap=None は従来通り（後方互換）
# ---------------------------------------------------------------------------

def test_6_no_pid_remap_preserves_original_pid():
    """pid_remap=None のとき source_pid がそのまま保存されること（後方互換）。"""
    f_export = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    f_export.close()

    try:
        wh_src = WinHistory()
        wh_src.record("当選Z", SRC_PID, roulette_id=RID1)
        wh_src.export_to_json(f_export.name, pattern_id=None, roulette_id=RID1)

        wh_dst = WinHistory()
        wh_dst.import_from_json(
            f_export.name,
            target_roulette_id=RID2,
            pid_remap=None,  # 明示的に None
        )

        assert wh_dst.records[0]["pattern_id"] == SRC_PID, (
            f"pid_remap=None の場合は source_pid が保持されるべき。"
            f"実際: {wh_dst.records[0]['pattern_id']}"
        )

    finally:
        os.unlink(f_export.name)


# ---------------------------------------------------------------------------
#  メインランナー
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_1_pid_remap_converts_source_to_dest,
        test_2_imported_log_visible_via_dest_pid,
        test_3_source_pid_not_stored,
        test_4_multiple_import_last_wins,
        test_5_cross_roulette_dedup_with_pid_remap,
        test_6_no_pid_remap_preserves_original_pid,
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
    if failed:
        print(f"{failed} test(s) FAILED.")
        sys.exit(1)
    else:
        print(f"All {len(tests)} tests passed.")
