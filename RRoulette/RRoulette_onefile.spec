# -*- mode: python ; coding: utf-8 -*-
# onefile 版 spec — 単一 EXE として全ファイルを埋め込む
# 起動時に %TEMP%\MEI{hash}\ へ展開するため初回起動は遅い（Windows Defender が毎回スキャン）
# 配布の手軽さを優先する場合に使用する
import os
from PyInstaller.utils.hooks import collect_all

# ─── 不要 DLL の除外リスト ───────────────────────────────────────────────────
_EXCLUDE_DLL_PREFIXES = (
    'Qt6WebEngine',
    'Qt6Quick',
    'Qt6Qml',
    'Qt63D',
    'Qt6Bluetooth',
    'Qt6Charts',
    'Qt6DataVisualization',
    'Qt6Designer',
    'Qt6Location',
    'Qt6Multimedia',
    'Qt6Nfc',
    'Qt6Pdf',
    'Qt6Positioning',
    'Qt6PrintSupport',
    'Qt6RemoteObjects',
    'Qt6Scxml',
    'Qt6Sensors',
    'Qt6SerialPort',
    'Qt6ShaderTools',
    'Qt6StateMachine',
    'Qt6TextToSpeech',
    'Qt6VirtualKeyboard',
    'Qt6WebChannel',
    'Qt6WebView',
    'Qt6Concurrent',
    'Qt6Test',
    'Qt6DBus',
)

_EXCLUDE_DEST_DIRS = (
    'PIL',
    'numpy',
    'PySide6/resources',
    'PySide6/translations',
    'PySide6/qml',
    'PySide6/metatypes',
    'PySide6/include',
    'PySide6/doc',
    'PySide6/glue',
    'PySide6/typesystems',
    'PySide6/scripts',
    'PySide6/support',
)


def _keep_binary(entry):
    dest = entry[0]
    name = os.path.basename(dest).lower()
    if any(name.startswith(p.lower()) for p in _EXCLUDE_DLL_PREFIXES):
        return False
    dest_norm = dest.replace('\\', '/')
    return not any(
        dest_norm.startswith(d + '/') or dest_norm == d
        for d in _EXCLUDE_DEST_DIRS
    )


def _keep_data(entry):
    dest_norm = entry[0].replace('\\', '/')
    return not any(
        dest_norm.startswith(d + '/') or dest_norm.startswith(d + '\\') or dest_norm == d
        for d in _EXCLUDE_DEST_DIRS
    )


datas = [("sounds", "sounds")]
binaries = []
hiddenimports = []

tmp_ret = collect_all('PySide6')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('pygame')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('winsdk')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['main.py'],
    pathex=['pyside6'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports + [
        'appdirs',
        'pkg_resources',
        'pkg_resources.extern',
        'setuptools',
        'setuptools._vendor',
        'setuptools._vendor.appdirs',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'numpy',
        'PIL',
        'Pillow',
        'PySide6.QtWebEngine',
        'PySide6.QtWebEngineCore',
        'PySide6.QtWebEngineWidgets',
        'PySide6.QtQuick',
        'PySide6.QtQuickControls2',
        'PySide6.QtQuickWidgets',
        'PySide6.QtQml',
        'PySide6.Qt3DCore',
        'PySide6.Qt3DAnimation',
        'PySide6.Qt3DExtras',
        'PySide6.Qt3DInput',
        'PySide6.Qt3DLogic',
        'PySide6.Qt3DRender',
        'PySide6.QtBluetooth',
        'PySide6.QtCharts',
        'PySide6.QtDataVisualization',
        'PySide6.QtDesigner',
        'PySide6.QtLocation',
        'PySide6.QtMultimedia',
        'PySide6.QtMultimediaWidgets',
        'PySide6.QtNfc',
        'PySide6.QtPdf',
        'PySide6.QtPdfWidgets',
        'PySide6.QtPositioning',
        'PySide6.QtPrintSupport',
        'PySide6.QtRemoteObjects',
        'PySide6.QtScxml',
        'PySide6.QtSensors',
        'PySide6.QtSerialPort',
        'PySide6.QtShaderTools',
        'PySide6.QtStateMachine',
        'PySide6.QtTextToSpeech',
        'PySide6.QtVirtualKeyboard',
        'PySide6.QtWebChannel',
        'PySide6.QtWebView',
        'PySide6.QtConcurrent',
        'PySide6.QtTest',
        'PySide6.QtDBus',
    ],
    noarchive=False,
    optimize=0,
)

a.binaries = [b for b in a.binaries if _keep_binary(b)]
a.datas    = [d for d in a.datas    if _keep_data(d)]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    name='RRoulette',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
