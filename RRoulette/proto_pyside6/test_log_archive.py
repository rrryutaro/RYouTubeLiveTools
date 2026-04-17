"""
i414 テスト: ログアーカイブ同一 roulette 専用化

## テスト内容

テスト1: export_to_json に source_roulette_id が含まれること
テスト2: 同一 roulette の export → clear → import で復元されること
テスト3: 同じアーカイブを再 import すると重複スキップされること
テスト4: 別 roulette のアーカイブは import_from_json レイヤーで判定可能（source_roulette_id 取得）
テスト5: _on_log_import が source_roulette_id 不一致時にガードすること（ソース解析）
テスト6: _on_log_import が pid_remap を渡さなくなったこと（ソース解析）
テスト7: pattern rename 後でも同一 roulette の既存ログ表示が壊れないこと
テスト8: pattern export/import の挙動が壊れていないこと（回帰）

実行方法:
  cd RRoulette/proto_pyside6
  set QT_QPA_PLATFORM=offscreen && python test_log_archive.py
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

PID1 = "pid-i414-r1-0001-000000000001"
RID1 = "roulette-i414-001"
RID2 = "roulette-i414-002"


# ---------------------------------------------------------------------------
#  テスト1: export_to_json に source_roulette_id が含まれること
# ---------------------------------------------------------------------------

def test_1_export_contains_source_roulette_id():
    """export_to_json が source_roulette_id をファイルに書き出すこと。"""
    f = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    f.close()
    try:
        wh = WinHistory()
        wh.record("当選A", PID1, roulette_id=RID1)
        wh.export_to_json(f.name, pattern_id=None, roulette_id=RID1)

        with open(f.name, encoding="utf-8") as fp:
            data = json.load(fp)

        assert "source_roulette_id" in data, (
            "export_to_json の出力に source_roulette_id キーが必要"
        )
        assert data["source_roulette_id"] == RID1, (
            f"source_roulette_id が {RID1} であるべき。実際: {data['source_roulette_id']}"
        )
    finally:
        os.unlink(f.name)


def test_1b_export_with_none_roulette_id():
    """roulette_id=None で export した場合 source_roulette_id が None になること。"""
    f = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    f.close()
    try:
        wh = WinHistory()
        wh.record("当選A", PID1, roulette_id=RID1)
        wh.export_to_json(f.name, pattern_id=None, roulette_id=None)

        with open(f.name, encoding="utf-8") as fp:
            data = json.load(fp)

        assert data.get("source_roulette_id") is None, (
            "roulette_id=None で export すると source_roulette_id は null のはず"
        )
    finally:
        os.unlink(f.name)


# ---------------------------------------------------------------------------
#  テスト2: 同一 roulette の export → clear → import で復元される
# ---------------------------------------------------------------------------

def test_2_same_roulette_restore():
    """同一 roulette で export → clear → import すると元の件数が復元されること。"""
    f = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    f.close()
    try:
        wh = WinHistory()
        wh.record("当選A", PID1, roulette_id=RID1, pattern_name="パターン1")
        wh.record("当選B", PID1, roulette_id=RID1, pattern_name="パターン1")
        wh.record("当選C", PID1, roulette_id=RID1, pattern_name="パターン1")

        # export
        wh.export_to_json(f.name, pattern_id=None, roulette_id=RID1)

        # clear
        wh.clear(roulette_id=RID1)
        assert len(wh.records) == 0, "クリア後は0件のはず"

        # restore（同一 roulette: target_roulette_id=None, pid_remap=None）
        added = wh.import_from_json(f.name)
        assert added == 3, f"3件復元されるはず。実際: {added}"

        # 全件 RID1 で集計できる
        counts = wh.count_by_item(PID1, roulette_id=RID1)
        assert counts == {"当選A": 1, "当選B": 1, "当選C": 1}, (
            f"復元後の集計が正しくない: {counts}"
        )
    finally:
        os.unlink(f.name)


# ---------------------------------------------------------------------------
#  テスト3: 同じアーカイブを再 import → 重複スキップ
# ---------------------------------------------------------------------------

def test_3_reimport_deduplicated():
    """同じアーカイブを 2 回 import すると 2 回目はスキップされること。"""
    f = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    f.close()
    try:
        wh = WinHistory()
        wh.record("当選A", PID1, roulette_id=RID1)
        wh.record("当選B", PID1, roulette_id=RID1)
        wh.export_to_json(f.name, pattern_id=None, roulette_id=RID1)
        wh.clear(roulette_id=RID1)

        added1 = wh.import_from_json(f.name)
        added2 = wh.import_from_json(f.name)

        assert added1 == 2, f"1回目は2件: {added1}"
        assert added2 == 0, f"2回目は重複で0件: {added2}"
        assert wh.total_count(PID1, roulette_id=RID1) == 2, "合計は2件のまま"
    finally:
        os.unlink(f.name)


# ---------------------------------------------------------------------------
#  テスト4: アーカイブから source_roulette_id を読み取れること
# ---------------------------------------------------------------------------

def test_4_read_source_roulette_id_from_archive():
    """export したファイルから source_roulette_id を正しく読み取れること。"""
    f = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    f.close()
    try:
        wh = WinHistory()
        wh.record("当選A", PID1, roulette_id=RID1)
        wh.export_to_json(f.name, pattern_id=None, roulette_id=RID1)

        with open(f.name, encoding="utf-8") as fp:
            archive = json.load(fp)

        source_rid = archive.get("source_roulette_id")
        active_rid = RID1

        assert source_rid == active_rid, (
            f"同一 roulette 判定: source_rid({source_rid}) == active_rid({active_rid})"
        )

        # 別 roulette との判定
        other_rid = RID2
        assert source_rid != other_rid, (
            "別 roulette とは不一致になるべき"
        )
    finally:
        os.unlink(f.name)


# ---------------------------------------------------------------------------
#  テスト5: _on_log_import が roulette_id 不一致ガードを持つこと（ソース解析）
# ---------------------------------------------------------------------------

def test_5_on_log_import_has_roulette_guard():
    """_on_log_import が source_roulette_id 不一致時にガードするコードを持つこと。"""
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

    body = find_func_body("_on_log_import")
    body_text = "\n".join(body)

    assert "source_roulette_id" in body_text, (
        "_on_log_import が source_roulette_id をチェックしていない"
    )
    assert "active_rid" in body_text or "active_id" in body_text, (
        "_on_log_import が active roulette ID と比較していない"
    )
    assert "インポートできません" in body_text or "取り込めません" in body_text, (
        "_on_log_import が roulette 不一致時の警告メッセージを持っていない"
    )
    assert "別のルーレット" in body_text, (
        "_on_log_import が別 roulette であることをメッセージで伝えていない"
    )


# ---------------------------------------------------------------------------
#  テスト6: _on_log_import が pid_remap を渡さなくなったこと（ソース解析）
# ---------------------------------------------------------------------------

def test_6_on_log_import_no_pid_remap():
    """_on_log_import が pid_remap を import_from_json に渡していないこと。"""
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

    body = find_func_body("_on_log_import")
    body_text = "\n".join(body)

    # import_from_json 呼び出しに pid_remap= 引数が渡されていないこと
    assert "pid_remap=" not in body_text, (
        "_on_log_import が pid_remap= を import_from_json に渡している。\n"
        "i414 で cross-roulette merge は log import 主経路から外すこと。"
    )
    # import_from_json 呼び出しに target_roulette_id= 引数が渡されていないこと
    assert "target_roulette_id=" not in body_text, (
        "_on_log_import が target_roulette_id= を import_from_json に渡している。\n"
        "同一 roulette 復元では roulette_id 上書きは不要。"
    )


# ---------------------------------------------------------------------------
#  テスト7: pattern rename 後でも同一 roulette の既存ログ表示が壊れないこと
# ---------------------------------------------------------------------------

def test_7_rename_does_not_break_same_roulette_log():
    """pattern rename 後でも pattern_id が維持されれば同一 roulette のログが見えること。"""
    wh = WinHistory()
    wh.record("当選A", PID1, roulette_id=RID1, pattern_name="元パターン名")
    wh.record("当選B", PID1, roulette_id=RID1, pattern_name="元パターン名")

    # rename 後も pattern_id は同じ → 集計に影響しない
    counts = wh.count_by_item(PID1, roulette_id=RID1)
    assert counts == {"当選A": 1, "当選B": 1}, (
        f"rename 前後で pattern_id が変わらない限りログは見えるべき: {counts}"
    )

    # rename 後にログ再記録（新 pattern_name で記録されるが PID1 は変わらない）
    wh.record("当選C", PID1, roulette_id=RID1, pattern_name="新パターン名")
    counts_after = wh.count_by_item(PID1, roulette_id=RID1)
    assert counts_after == {"当選A": 1, "当選B": 1, "当選C": 1}, (
        f"rename 後も同 PID1 で集計できるべき: {counts_after}"
    )


# ---------------------------------------------------------------------------
#  テスト8: pattern export/import の回帰確認
# ---------------------------------------------------------------------------

def test_8_pattern_io_not_broken():
    """pattern export/import の既存動作が壊れていないこと（ソース解析）。"""
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

    # pattern export に pattern_id が含まれること（i411 維持）
    export_body = "\n".join(find_func_body("_on_pattern_export"))
    assert '"pattern_id"' in export_body or "'pattern_id'" in export_body, (
        "_on_pattern_export が pattern_id を出力していない"
    )

    # pattern import が item_patterns 分岐を持つこと（i410 維持）
    import_body = "\n".join(find_func_body("_on_pattern_import"))
    assert "ctx.item_patterns is not None" in import_body, (
        "_on_pattern_import の non-default 分岐が消えている"
    )


# ---------------------------------------------------------------------------
#  メインランナー
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_1_export_contains_source_roulette_id,
        test_1b_export_with_none_roulette_id,
        test_2_same_roulette_restore,
        test_3_reimport_deduplicated,
        test_4_read_source_roulette_id_from_archive,
        test_5_on_log_import_has_roulette_guard,
        test_6_on_log_import_no_pid_remap,
        test_7_rename_does_not_break_same_roulette_log,
        test_8_pattern_io_not_broken,
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
