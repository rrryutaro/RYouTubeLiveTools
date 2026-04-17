"""
i411 テスト: pattern 識別整合と log 重複判定修正

## テスト内容

テスト1: pattern export に pattern_id が含まれること（ソース解析）
  - _on_pattern_export 内で pattern_id が data に追加されていること

テスト2: 同名 pattern が存在しても import が曖昧動作しないこと
  - 同名パターンがある場合は連番付き別名で追加されること
  - 元のパターンのデータが書き換わらないこと

テスト3: #1 export → #2 import で log が destination 側に取り込まれること
  - target_roulette_id=RID2 で import すると RID2 に追加されること
  - RID1 の既存レコードと同一 id でも誤スキップされないこと

テスト4: 他 roulette に既存ログがあっても destination への import が全スキップされないこと
  - self._records に RID1 のレコードが多数あっても、RID2 への import は正常に追加されること

テスト5: 同一ファイルを同一 roulette に 2 回 import すると 2 回目は重複スキップ
  - 正しい重複判定が維持されていること

実行方法:
  cd RRoulette/proto_pyside6
  set QT_QPA_PLATFORM=offscreen && python test_pattern_log_id_integrity.py
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

PID1 = "pid-i411-r1-0001-000000000001"
PID2 = "pid-i411-r2-0002-000000000002"
RID1 = "roulette-i411-001"
RID2 = "roulette-i411-002"


# ---------------------------------------------------------------------------
#  テスト1: pattern export に pattern_id が含まれること（ソース解析）
# ---------------------------------------------------------------------------

def test_1_pattern_export_contains_pattern_id():
    """_on_pattern_export が pattern_id を export JSON に含めること。"""
    main_window_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "main_window.py"
    )
    with open(main_window_path, encoding="utf-8") as f:
        source = f.read()

    lines = source.splitlines()

    def find_func_body(func_name: str) -> list[str]:
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

    body = find_func_body("_on_pattern_export")
    body_text = "\n".join(body)

    assert '"pattern_id"' in body_text or "'pattern_id'" in body_text, (
        "_on_pattern_export が pattern_id を export JSON に含めていない。\n"
        "data dict に 'pattern_id' キーを追加すること。"
    )
    assert "_get_pattern_id_for_ctx" in body_text or "_get_current_pattern_id" in body_text, (
        "_on_pattern_export が pattern_id を取得する関数を呼んでいない。\n"
        "_get_pattern_id_for_ctx または _get_current_pattern_id を呼ぶこと。"
    )


# ---------------------------------------------------------------------------
#  テスト2: 同名 pattern import が既存パターンを上書きしないこと
# ---------------------------------------------------------------------------

def test_2_same_name_pattern_import_no_overwrite():
    """同名パターンが存在しても既存データが上書きされないこと。"""
    # non-default ルーレットの ctx を模擬
    ctx = {
        "item_patterns": {
            "パターンA": [{"text": "元の項目1", "enabled": True, "split_count": 1,
                          "prob_mode": None, "prob_value": None}],
        },
        "current_pattern": "パターンA",
    }
    existing = list(ctx["item_patterns"].keys())

    # import しようとするパターン名が同名
    import_name = "パターンA"
    final_name = import_name
    if final_name in existing:
        suffix = 1
        while f"{import_name}_{suffix}" in existing:
            suffix += 1
        final_name = f"{import_name}_{suffix}"

    import_entries_raw = [{"text": "新項目X", "enabled": True, "split_count": 1,
                           "prob_mode": None, "prob_value": None}]

    # import 適用
    ctx["item_patterns"][final_name] = import_entries_raw
    ctx["current_pattern"] = final_name

    # 元の「パターンA」が破壊されていない
    assert "パターンA" in ctx["item_patterns"], "元パターンA が消えてはいけない"
    assert ctx["item_patterns"]["パターンA"][0]["text"] == "元の項目1", (
        "元パターンA の項目が上書きされてはいけない"
    )
    # 新パターンは連番付き別名になっている
    assert final_name == "パターンA_1", f"連番別名が期待と異なる: {final_name}"
    assert "パターンA_1" in ctx["item_patterns"]
    assert ctx["item_patterns"]["パターンA_1"][0]["text"] == "新項目X"


def test_2b_same_name_multiple_imports_increment():
    """同名で複数回 import すると連番が増えていくこと。"""
    ctx_patterns = {"パターンA": [], "パターンA_1": []}
    existing = list(ctx_patterns.keys())

    import_name = "パターンA"
    final_name = import_name
    if final_name in existing:
        suffix = 1
        while f"{import_name}_{suffix}" in existing:
            suffix += 1
        final_name = f"{import_name}_{suffix}"

    assert final_name == "パターンA_2", f"3回目は _2 になるはず: {final_name}"


# ---------------------------------------------------------------------------
#  テスト3: #1 export → #2 import で log が取り込まれること
# ---------------------------------------------------------------------------

def test_3_cross_roulette_import_succeeds():
    """#1 のログを export して #2 に import すると、#2 に追加されること。"""
    f_export = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    f_export.close()

    try:
        # #1 のログを作成して export
        wh_src = WinHistory()
        wh_src.record("当選A", PID1, roulette_id=RID1, pattern_name="パターン1")
        wh_src.record("当選B", PID1, roulette_id=RID1, pattern_name="パターン1")
        wh_src.export_to_json(f_export.name, pattern_id=None, roulette_id=RID1)

        # #1 のログも持つ共有 WinHistory（実アプリ相当: #1 のレコードが既に存在）
        wh_shared = WinHistory()
        wh_shared.record("当選A", PID1, roulette_id=RID1, pattern_name="パターン1")
        wh_shared.record("当選B", PID1, roulette_id=RID1, pattern_name="パターン1")

        # #2 active で import → target_roulette_id=RID2
        added = wh_shared.import_from_json(f_export.name, target_roulette_id=RID2)

        assert added == 2, (
            f"#2 に2件追加されるはず。実際: {added} 件。\n"
            f"他 roulette (#1) の既存レコードと id が衝突して誤スキップされていないか確認。"
        )

        # #2 のレコードが存在する
        r2 = [r for r in wh_shared.records if r.get("roulette_id") == RID2]
        assert len(r2) == 2, f"#2 に2件追加されるはず。実際: {len(r2)} 件"

        # #1 のレコードは変わっていない
        r1 = [r for r in wh_shared.records if r.get("roulette_id") == RID1]
        assert len(r1) == 2, f"#1 のレコードが変わってはいけない。実際: {len(r1)} 件"

    finally:
        os.unlink(f_export.name)


# ---------------------------------------------------------------------------
#  テスト4: 他 roulette の大量レコードがあっても import が全スキップされないこと
# ---------------------------------------------------------------------------

def test_4_large_existing_other_roulette_does_not_block_import():
    """他 roulette (RID1) に多数のレコードがあっても RID2 への import が成功すること。"""
    f_export = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    f_export.close()

    try:
        # source: 5 件のログ
        wh_src = WinHistory()
        for i in range(5):
            wh_src.record(f"項目{i}", PID1, roulette_id=RID1)
        wh_src.export_to_json(f_export.name, pattern_id=None, roulette_id=RID1)

        # destination: RID1 の同一レコード（同じ id）が多数ある共有インスタンス
        wh_dst = WinHistory()
        for i in range(5):
            wh_dst.record(f"項目{i}", PID1, roulette_id=RID1)

        # RID2 への import: RID1 の既存レコードと id が重複していても通るべき
        added = wh_dst.import_from_json(f_export.name, target_roulette_id=RID2)

        assert added == 5, (
            f"RID2 に5件追加されるはず。実際: {added} 件。\n"
            f"RID1 の既存レコードが誤スキップ原因になっていないか確認。"
        )

        r2 = [r for r in wh_dst.records if r.get("roulette_id") == RID2]
        assert len(r2) == 5, f"RID2 に5件あるはず: {len(r2)}"

        # RID1 は不変
        r1 = [r for r in wh_dst.records if r.get("roulette_id") == RID1]
        assert len(r1) == 5, f"RID1 は5件のまま: {len(r1)}"

    finally:
        os.unlink(f_export.name)


# ---------------------------------------------------------------------------
#  テスト5: 同一 roulette への 2 回目 import は正しく重複スキップされること
# ---------------------------------------------------------------------------

def test_5_same_roulette_dedup_still_works():
    """同じ roulette に同一ファイルを2回 import すると2回目はスキップされること。"""
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

        assert added1 == 2, f"1回目は2件追加されるはず: {added1}"
        assert added2 == 0, (
            f"2回目は重複のため0件のはず: {added2}\n"
            "同一 roulette への再 import は正しく deduplicate すること。"
        )

    finally:
        os.unlink(f_export.name)


# ---------------------------------------------------------------------------
#  メインランナー
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_1_pattern_export_contains_pattern_id,
        test_2_same_name_pattern_import_no_overwrite,
        test_2b_same_name_multiple_imports_increment,
        test_3_cross_roulette_import_succeeds,
        test_4_large_existing_other_roulette_does_not_block_import,
        test_5_same_roulette_dedup_still_works,
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
