"""
i408 テスト: ログ入出力の roulette 単位保証 / ファイルダイアログ既定フォルダ統一

## テスト内容

テストA: multi 環境での export スコープ確認
  - #1 / #2 に別々のログを持たせ、#1 active で export すると #1 のみ書き出される

テストB: import が active roulette のみに反映されること
  - target_roulette_id を指定して import すると、指定 roulette にのみ帰属する
  - 他 roulette には追加されない

テストC: import 後に active roulette の集計が正しく更新される
  - import 後に count_by_item / total_count が新規レコードを反映する

テストD: EXPORT_DIR 定数が統一されていること
  - main_window.py の EXPORT_DIR が定義されており、
    pattern export / import / log export / import が共通で参照していること

実行方法:
  cd RRoulette/proto_pyside6
  set QT_QPA_PLATFORM=offscreen && python test_log_io_roulette_scope.py
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

PID1 = "pid-r1-0001-0001-000000000001"
PID2 = "pid-r2-0002-0002-000000000002"
RID1 = "roulette-id-001"
RID2 = "roulette-id-002"


# ---------------------------------------------------------------------------
#  テストA: export スコープが active roulette 単位で閉じること
# ---------------------------------------------------------------------------

def test_a_export_scoped_to_active_roulette():
    """#1 active で export すると #1 のログのみ書き出され、#2 のログは含まれない。"""
    f_export = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    f_export.close()

    try:
        wh = WinHistory()
        # #1 のログ 2 件
        wh.record("当選A", PID1, roulette_id=RID1, pattern_name="パターン1")
        wh.record("当選B", PID1, roulette_id=RID1, pattern_name="パターン1")
        # #2 のログ 1 件
        wh.record("当選C", PID2, roulette_id=RID2, pattern_name="パターン2")

        # #1 active で全パターンエクスポート (export_pid=None, export_rid=RID1)
        wh.export_to_json(f_export.name, pattern_id=None, roulette_id=RID1)

        with open(f_export.name, encoding="utf-8") as f:
            data = json.load(f)
        exported = data.get("records", [])

        assert len(exported) == 2, (
            f"#1 active export は2件のはず。実際: {len(exported)} 件。"
            f"#2 のログが混ざっていないか確認すること。"
        )
        for rec in exported:
            assert rec.get("roulette_id") == RID1, (
                f"export に #2 のレコードが混入: {rec}"
            )
    finally:
        os.unlink(f_export.name)


def test_a2_export_all_patterns_still_scoped_to_roulette():
    """全パターンモードでも roulette_id スコープが外れないこと（i408 コアバグ修正確認）。"""
    f_export = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    f_export.close()

    try:
        wh = WinHistory()
        wh.record("A_r1", PID1, roulette_id=RID1, pattern_name="パターン1")
        wh.record("B_r1", PID2, roulette_id=RID1, pattern_name="パターン2")  # 別パターン, 同じ #1
        wh.record("C_r2", PID1, roulette_id=RID2, pattern_name="パターン1")  # #2 のログ

        # 全パターンモード相当: pattern_id=None (全パターン), roulette_id=RID1 (active roulette)
        wh.export_to_json(f_export.name, pattern_id=None, roulette_id=RID1)

        with open(f_export.name, encoding="utf-8") as f:
            data = json.load(f)
        exported = data.get("records", [])

        # #1 の2件のみ、#2 の1件は含まれない
        assert len(exported) == 2, (
            f"全パターン+#1 active なら2件のはず。実際: {len(exported)} 件。"
            f"#2 が混ざっていないか確認すること。i408 の roulette_id=None バグが直っていれば3件にはならない。"
        )
        for rec in exported:
            assert rec.get("roulette_id") == RID1, (
                f"#2 のレコードが混入: {rec}"
            )
    finally:
        os.unlink(f_export.name)


# ---------------------------------------------------------------------------
#  テストB: import が active roulette のみに反映される
# ---------------------------------------------------------------------------

def test_b_import_only_to_target_roulette():
    """#2 active で import した時、#2 にのみ追加され #1 は不変であること。"""
    f_export = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    f_export.close()

    try:
        # #1 のログを export
        wh_src = WinHistory()
        wh_src.record("当選A", PID1, roulette_id=RID1, pattern_name="パターン1")
        wh_src.record("当選B", PID1, roulette_id=RID1, pattern_name="パターン1")
        wh_src.export_to_json(f_export.name, pattern_id=None, roulette_id=RID1)

        # #2 active の状態で import: target_roulette_id=RID2 を指定
        wh_dst = WinHistory()
        wh_dst.record("既存X", PID2, roulette_id=RID2, pattern_name="パターン2")

        added = wh_dst.import_from_json(f_export.name, target_roulette_id=RID2)
        assert added == 2, f"#2 に2件追加されるはず。実際: {added}"

        # #2 のレコードは 3 件 (既存1 + 追加2)
        r2 = [r for r in wh_dst.records if r.get("roulette_id") == RID2]
        assert len(r2) == 3, f"#2 のレコードは3件のはず。実際: {len(r2)}"

        # #1 のレコードは 0 件（混入していない）
        r1 = [r for r in wh_dst.records if r.get("roulette_id") == RID1]
        assert len(r1) == 0, (
            f"#1 にレコードが混入している。実際: {len(r1)} 件。"
            f"target_roulette_id 上書きが機能していれば #1 には何も入らないはず。"
        )
    finally:
        os.unlink(f_export.name)


def test_b2_import_without_target_keeps_original_roulette_id():
    """target_roulette_id=None の場合は元の roulette_id を保持する（後方互換）。"""
    f_export = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    f_export.close()

    try:
        wh_src = WinHistory()
        wh_src.record("当選A", PID1, roulette_id=RID1)
        wh_src.export_to_json(f_export.name, pattern_id=None, roulette_id=None)

        wh_dst = WinHistory()
        added = wh_dst.import_from_json(f_export.name, target_roulette_id=None)
        assert added == 1

        # 元の roulette_id が保たれる
        assert wh_dst.records[0]["roulette_id"] == RID1, (
            f"target_roulette_id=None 時は元の roulette_id を維持するはず。"
            f"実際: {wh_dst.records[0]['roulette_id']}"
        )
    finally:
        os.unlink(f_export.name)


# ---------------------------------------------------------------------------
#  テストC: import 後に active roulette の集計が反映される
# ---------------------------------------------------------------------------

def test_c_import_updates_count():
    """import 後に count_by_item / total_count が新規レコードを反映すること。"""
    f_export = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    f_export.close()

    try:
        # #1 のログ (PID1: 当選A x2, 当選B x1)
        wh_src = WinHistory()
        wh_src.record("当選A", PID1, roulette_id=RID1)
        wh_src.record("当選A", PID1, roulette_id=RID1)
        wh_src.record("当選B", PID1, roulette_id=RID1)
        wh_src.export_to_json(f_export.name, pattern_id=None, roulette_id=RID1)

        # #2 に import
        wh = WinHistory()
        wh.import_from_json(f_export.name, target_roulette_id=RID2)

        # #2 / PID1 の集計
        counts = wh.count_by_item(PID1, roulette_id=RID2)
        assert counts == {"当選A": 2, "当選B": 1}, (
            f"import 後に集計が反映されるはず。実際: {counts}"
        )

        total = wh.total_count(PID1, roulette_id=RID2)
        assert total == 3, f"合計3件のはず。実際: {total}"

        # #1 には何も入っていない
        counts_r1 = wh.count_by_item(PID1, roulette_id=RID1)
        assert counts_r1 == {}, (
            f"#1 は空のはず。実際: {counts_r1}"
        )
    finally:
        os.unlink(f_export.name)


def test_c2_import_dedup_does_not_double_count():
    """同じファイルを 2 回 import しても件数が重複しないこと。"""
    f_export = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    f_export.close()

    try:
        wh_src = WinHistory()
        wh_src.record("当選A", PID1, roulette_id=RID1)
        wh_src.record("当選B", PID1, roulette_id=RID1)
        wh_src.export_to_json(f_export.name, pattern_id=None, roulette_id=RID1)

        wh = WinHistory()
        added1 = wh.import_from_json(f_export.name, target_roulette_id=RID2)
        added2 = wh.import_from_json(f_export.name, target_roulette_id=RID2)

        assert added1 == 2, f"1回目は2件追加: {added1}"
        assert added2 == 0, f"2回目は重複のため0件: {added2}"
        assert wh.total_count(PID1, roulette_id=RID2) == 2, "合計は2件のまま"
    finally:
        os.unlink(f_export.name)


# ---------------------------------------------------------------------------
#  テストD: EXPORT_DIR 定数が main_window で統一されていること
# ---------------------------------------------------------------------------

def test_d_export_dir_defined_in_main_window():
    """EXPORT_DIR 定数が main_window.py に定義されていること。"""
    import ast

    main_window_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "main_window.py"
    )
    assert os.path.exists(main_window_path), "main_window.py が見つからない"

    with open(main_window_path, encoding="utf-8") as f:
        source = f.read()

    # EXPORT_DIR が定義されているか
    assert "EXPORT_DIR" in source, "EXPORT_DIR が main_window.py に定義されていない"


def test_d2_export_dir_used_in_all_dialogs():
    """EXPORT_DIR が pattern/log の export/import 4 箇所全てで参照されていること。"""
    main_window_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "main_window.py"
    )
    with open(main_window_path, encoding="utf-8") as f:
        source = f.read()

    # _on_pattern_export: EXPORT_DIR を使って getSaveFileName を呼んでいる
    assert "EXPORT_DIR" in source, "EXPORT_DIR 参照なし"

    # 各関数内の使用箇所を行単位で確認
    lines = source.splitlines()

    def find_func_body(func_name: str) -> list[str]:
        """指定メソッド名の定義以降 次の def まで取得する。"""
        in_func = False
        body = []
        for line in lines:
            if f"def {func_name}(" in line:
                in_func = True
            elif in_func and line.strip().startswith("def ") and f"def {func_name}(" not in line:
                break
            if in_func:
                body.append(line)
        return body

    for func_name in [
        "_on_pattern_export",
        "_on_pattern_import",
        "_on_log_export",
        "_on_log_import",
    ]:
        body = find_func_body(func_name)
        assert body, f"{func_name} が main_window.py に見つからない"
        body_text = "\n".join(body)
        assert "EXPORT_DIR" in body_text, (
            f"{func_name} が EXPORT_DIR を参照していない。"
            f"i408: 4 箇所全てで EXPORT_DIR を使うこと。"
        )


# ---------------------------------------------------------------------------
#  メインランナー
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_a_export_scoped_to_active_roulette,
        test_a2_export_all_patterns_still_scoped_to_roulette,
        test_b_import_only_to_target_roulette,
        test_b2_import_without_target_keeps_original_roulette_id,
        test_c_import_updates_count,
        test_c2_import_dedup_does_not_double_count,
        test_d_export_dir_defined_in_main_window,
        test_d2_export_dir_used_in_all_dialogs,
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
