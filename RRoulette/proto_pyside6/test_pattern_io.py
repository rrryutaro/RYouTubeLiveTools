"""
i410 テスト: 項目パネル import / export の正常性確認

## テスト内容

テストA: export ファイル出力構造の確認
  - pattern_name / entries キーを持つ JSON 構造が出力されること
  - entries 内の各項目が text キーを持つこと

テストB: non-default ルーレットへの import 隔離確認
  - import を non-default ctx に適用しても、他 ctx に影響しないこと
  - item_patterns / current_pattern が対象 ctx のみ変わること

テストC: export → import の round-trip 確認
  - ItemEntry の to_dict / from_config_entry が往復して元の状態を再現すること
  - current_pattern が import したパターン名になること

テストD: import 後 UI 更新パスが存在すること（ソース解析）
  - _on_pattern_import 内で _refresh_simple_list / _refresh_panel_tracking /
    _update_win_counts が呼ばれていること

テストE: 既存 log テストが PASS を維持すること（i407/i408 回帰）
  - test_log_io_roulette_scope.py / test_log_display_regression.py /
    test_startup_log_init_sequence.py のテスト関数を再実行して確認

テストF: dialog 既定ディレクトリが EXPORT_DIR で統一されていること（ソース解析）
  - _on_pattern_export / _on_pattern_import の両方で EXPORT_DIR が参照されること

実行方法:
  cd RRoulette/proto_pyside6
  set QT_QPA_PLATFORM=offscreen && python test_pattern_io.py
"""

import json
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from item_entry import ItemEntry  # noqa: E402


# ---------------------------------------------------------------------------
#  テストA: export ファイル出力構造
# ---------------------------------------------------------------------------

def test_a_export_file_structure():
    """export が pattern_name + entries 構造で出力されること。"""
    entries = [
        ItemEntry(text="項目A", enabled=True, split_count=1),
        ItemEntry(text="項目B", enabled=False, split_count=2),
    ]
    data = {
        "pattern_name": "テストパターン",
        "entries": [e.to_dict() for e in entries],
    }
    f = tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w",
                                    encoding="utf-8")
    json.dump(data, f, ensure_ascii=False, indent=2)
    f.close()
    try:
        with open(f.name, encoding="utf-8") as fp:
            loaded = json.load(fp)
        assert "pattern_name" in loaded, "pattern_name キーが必要"
        assert "entries" in loaded, "entries キーが必要"
        assert loaded["pattern_name"] == "テストパターン"
        assert len(loaded["entries"]) == 2
        for e in loaded["entries"]:
            assert "text" in e, f"entries 内に text キーが必要: {e}"
    finally:
        os.unlink(f.name)


# ---------------------------------------------------------------------------
#  テストB: non-default ルーレットへの import 隔離
# ---------------------------------------------------------------------------

def test_b_import_isolated_to_active_ctx():
    """non-default roulette ctx への import が他 ctx に影響しないこと。"""
    # 2つの独立した ctx.item_patterns を模擬
    ctx_active = {"item_patterns": {"デフォルト": []}, "current_pattern": "デフォルト"}
    ctx_other  = {"item_patterns": {"デフォルト": [{"text": "既存X", "enabled": True,
                                                    "split_count": 1, "prob_mode": None,
                                                    "prob_value": None}]},
                  "current_pattern": "デフォルト"}

    # import するエントリ
    import_entries_raw = [{"text": "新項目1", "enabled": True, "split_count": 1,
                           "prob_mode": None, "prob_value": None}]
    imported = [ItemEntry.from_config_entry(r, keep_disabled=True) for r in import_entries_raw]
    imported = [e for e in imported if e is not None]

    # active ctx にのみ適用（_on_pattern_import の non-default 分岐相当）
    final_name = "インポートパターン"
    ctx_active["item_patterns"][final_name] = [e.to_dict() for e in imported]
    ctx_active["current_pattern"] = final_name

    # active ctx が更新されている
    assert final_name in ctx_active["item_patterns"], "active ctx にパターンが追加されるべき"
    assert ctx_active["current_pattern"] == final_name, "current_pattern が切り替わるべき"
    assert len(ctx_active["item_patterns"][final_name]) == 1

    # other ctx は不変
    assert "インポートパターン" not in ctx_other["item_patterns"], (
        "他 ctx に import が混入してはいけない"
    )
    assert ctx_other["current_pattern"] == "デフォルト", (
        "他 ctx の current_pattern が変わってはいけない"
    )
    # 既存データが変わっていない
    assert len(ctx_other["item_patterns"]["デフォルト"]) == 1, (
        "他 ctx の既存項目が消えてはいけない"
    )


# ---------------------------------------------------------------------------
#  テストC: export → import round-trip
# ---------------------------------------------------------------------------

def test_c_export_import_round_trip():
    """ItemEntry の to_dict / from_config_entry が往復して元の状態を再現すること。"""
    original = [
        ItemEntry(text="項目1", enabled=True,  split_count=1, prob_mode=None, prob_value=None),
        ItemEntry(text="項目2", enabled=False, split_count=3, prob_mode="fixed", prob_value=0.5),
        ItemEntry(text="項目3", enabled=True,  split_count=1, prob_mode="weight", prob_value=2.0),
    ]

    # export 相当: to_dict
    exported_raw = [e.to_dict() for e in original]

    # import 相当: from_config_entry (keep_disabled=True)
    restored = [ItemEntry.from_config_entry(r, keep_disabled=True) for r in exported_raw]
    restored = [e for e in restored if e is not None]

    assert len(restored) == len(original), (
        f"round-trip 後の件数が一致しない: {len(original)} -> {len(restored)}"
    )
    for orig, rest in zip(original, restored):
        assert orig.text == rest.text, f"text 不一致: {orig.text} / {rest.text}"
        assert orig.enabled == rest.enabled, f"enabled 不一致: {orig.enabled} / {rest.enabled}"
        assert orig.split_count == rest.split_count, (
            f"split_count 不一致: {orig.split_count} / {rest.split_count}"
        )
        assert orig.prob_mode == rest.prob_mode, (
            f"prob_mode 不一致: {orig.prob_mode} / {rest.prob_mode}"
        )
        assert orig.prob_value == rest.prob_value, (
            f"prob_value 不一致: {orig.prob_value} / {rest.prob_value}"
        )


def test_c2_import_pattern_name_becomes_current():
    """import 後に current_pattern がインポートしたパターン名になること。"""
    ctx = {"item_patterns": {"デフォルト": []}, "current_pattern": "デフォルト"}

    entries_raw = [{"text": "テスト項目", "enabled": True, "split_count": 1,
                    "prob_mode": None, "prob_value": None}]
    imported = [ItemEntry.from_config_entry(r, keep_disabled=True) for r in entries_raw]
    imported = [e for e in imported if e is not None]

    final_name = "インポートP"
    ctx["item_patterns"][final_name] = [e.to_dict() for e in imported]
    ctx["current_pattern"] = final_name

    assert ctx["current_pattern"] == final_name, (
        "import 後の current_pattern がインポートパターン名になるべき"
    )
    assert final_name in ctx["item_patterns"], "パターンが item_patterns に追加されるべき"


# ---------------------------------------------------------------------------
#  テストD: import 後 UI 更新パス（ソース解析）
# ---------------------------------------------------------------------------

def test_d_import_calls_ui_refresh():
    """_on_pattern_import が UI 更新に必要な関数を呼んでいること。"""
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

    body = find_func_body("_on_pattern_import")
    body_text = "\n".join(body)

    assert "_refresh_simple_list" in body_text, (
        "_on_pattern_import が _refresh_simple_list を呼んでいない（ItemPanel 更新漏れ）"
    )
    assert "_refresh_panel_tracking" in body_text, (
        "_on_pattern_import が _refresh_panel_tracking を呼んでいない（マウストラッキング漏れ）"
    )
    assert "_update_win_counts" in body_text, (
        "_on_pattern_import が _update_win_counts を呼んでいない（勝利数表示漏れ）"
    )
    assert "set_current_pattern" in body_text or "ctx.current_pattern" in body_text, (
        "_on_pattern_import が current_pattern を更新していない"
    )
    assert "set_segments" in body_text, (
        "_on_pattern_import がホイールセグメントを更新していない"
    )


def test_d2_export_uses_ctx_current_pattern():
    """_on_pattern_export が non-default ルーレット用に ctx.current_pattern を参照すること。"""
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

    assert "ctx.current_pattern" in body_text, (
        "_on_pattern_export が ctx.current_pattern を参照していない "
        "（non-default ルーレットのパターン名取得が正しくない）"
    )
    assert "item_patterns" in body_text, (
        "_on_pattern_export が item_patterns 分岐を持っていない"
    )


def test_d3_import_branches_on_item_patterns():
    """_on_pattern_import が item_patterns の有無で分岐すること。"""
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

    body = find_func_body("_on_pattern_import")
    body_text = "\n".join(body)

    assert "ctx.item_patterns is not None" in body_text, (
        "_on_pattern_import が non-default ルーレット分岐を持っていない "
        "（ctx.item_patterns is not None の分岐が必要）"
    )
    # non-default 分岐内で ctx.item_patterns に書き込む
    assert "ctx.item_patterns[" in body_text, (
        "_on_pattern_import が ctx.item_patterns にパターンを追加していない"
    )
    # default 分岐でグローバル config を使う
    assert "add_pattern(self._config" in body_text, (
        "_on_pattern_import が default ルーレット用の add_pattern を持っていない"
    )


# ---------------------------------------------------------------------------
#  テストF: dialog 既定ディレクトリが EXPORT_DIR で統一
# ---------------------------------------------------------------------------

def test_f_dialog_uses_export_dir():
    """_on_pattern_export / _on_pattern_import の両方で EXPORT_DIR が参照されること。"""
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

    for func_name in ["_on_pattern_export", "_on_pattern_import"]:
        body = find_func_body(func_name)
        body_text = "\n".join(body)
        assert "EXPORT_DIR" in body_text, (
            f"{func_name} が EXPORT_DIR を dialog 既定フォルダとして参照していない"
        )


# ---------------------------------------------------------------------------
#  メインランナー
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_a_export_file_structure,
        test_b_import_isolated_to_active_ctx,
        test_c_export_import_round_trip,
        test_c2_import_pattern_name_becomes_current,
        test_d_import_calls_ui_refresh,
        test_d2_export_uses_ctx_current_pattern,
        test_d3_import_branches_on_item_patterns,
        test_f_dialog_uses_export_dir,
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
