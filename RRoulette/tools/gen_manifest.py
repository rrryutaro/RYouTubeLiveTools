"""
tools/gen_manifest.py — onedir 配布物の manifest.json を生成する（P0）

仕様: 自動アップデート機能 設計仕様 §13.1

onedir ビルド後に `dist/RRoulette/` を走査し、差分更新の基準となる
`manifest.json`（version / runtime_fingerprint / files{path: sha256}）を出力する。
生成物は zip に同梱し（現地基準）、リリース資産としても添付する。

使い方（RRoulette/ ディレクトリから）:
  python tools/gen_manifest.py
  python tools/gen_manifest.py --install-dir dist/RRoulette --version 0.6.5

依存は stdlib のみ（updater.build_manifest を再利用）。PySide6 は不要。
"""

import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_RROULETTE = os.path.normpath(os.path.join(_HERE, ".."))
_PYSIDE6 = os.path.join(_RROULETTE, "pyside6")
for _p in (_RROULETTE, _PYSIDE6):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import updater  # noqa: E402  (stdlib のみ・PySide6 非依存)

try:
    from constants import VERSION as _DEFAULT_VERSION
except Exception:  # pragma: no cover
    _DEFAULT_VERSION = "0.0.0"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="RRoulette onedir manifest 生成")
    ap.add_argument("--install-dir",
                    default=os.path.join(_RROULETTE, "dist", "RRoulette"),
                    help="onedir 配布物のルート（既定: dist/RRoulette）")
    ap.add_argument("--version", default=_DEFAULT_VERSION,
                    help="manifest に記録するバージョン（既定: constants.VERSION）")
    ap.add_argument("--out", default=None,
                    help="出力先（既定: <install-dir>/manifest.json）")
    args = ap.parse_args(argv)

    install = os.path.abspath(args.install_dir)
    exe = os.path.join(install, updater.APP_EXE_NAME)
    if not os.path.isfile(exe):
        print(f"ERROR: {install} に {updater.APP_EXE_NAME} が見つかりません。"
              f"onedir ビルド後に実行してください。", file=sys.stderr)
        return 2
    if not os.path.isdir(os.path.join(install, "_internal")):
        print(f"WARNING: {install} に _internal/ がありません（onedir 構造ではない可能性）",
              file=sys.stderr)

    manifest = updater.build_manifest(install, args.version)
    out = args.out or os.path.join(install, updater.MANIFEST_NAME)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(f"manifest 生成: {out}")
    print(f"  version={manifest['version']}  "
          f"files={len(manifest['files'])}  "
          f"runtime_fingerprint={manifest['runtime_fingerprint'][:16]}...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
