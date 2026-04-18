"""
RRoulette — テーマ適用基盤

画面全体の主要ウィジェットへ light / dark テーマを適用するためのスタイルシート生成。
DesignSettings のカラートークンを参照し、QApplication レベルで適用可能な
スタイルシートを返す。

将来の拡張ポイント:
  - OS テーマ検出: 呼び出し側で判定して切り替え
  - テーマプリセット: 複数配色セットの切替
"""

import sys

from design_settings import DesignSettings


def detect_os_theme() -> str:
    """OS のテーマ設定を検出して "light" or "dark" を返す。

    Windows: レジストリの AppsUseLightTheme を参照。
    判定不能時は "dark" にフォールバック。
    """
    if sys.platform == "win32":
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            )
            val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            winreg.CloseKey(key)
            return "light" if val == 1 else "dark"
        except Exception:
            return "dark"
    return "dark"


def resolve_theme_mode(theme_mode: str) -> str:
    """設定値を実効テーマ ("light" / "dark") に解決する。

    "system" / "auto" の場合は OS テーマを検出して返す。
    """
    if theme_mode in ("system", "auto"):
        return detect_os_theme()
    if theme_mode == "light":
        return "light"
    return "dark"


def dark_checkbox_style(d: DesignSettings) -> str:
    """ダークテーマ向け QCheckBox スタイル（個別適用用）。"""
    return (
        f"QCheckBox {{ color: {d.text}; spacing: 6px; }}"
        f"QCheckBox::indicator {{"
        f"  width: 14px; height: 14px;"
        f"  border: 1px solid {d.text_sub};"
        f"  border-radius: 2px;"
        f"  background-color: {d.panel};"
        f"}}"
        f"QCheckBox::indicator:checked {{"
        f"  background-color: {d.accent};"
        f"  border-color: {d.accent};"
        f"}}"
        f"QCheckBox::indicator:hover {{"
        f"  border-color: {d.text};"
        f"}}"
    )


def dark_spinbox_style(d: DesignSettings) -> str:
    """ダークテーマ向け QSpinBox / QDoubleSpinBox 共通スタイル（個別適用用）。"""
    return (
        f"QSpinBox, QDoubleSpinBox {{"
        f"  background-color: {d.separator}; color: {d.text};"
        f"  border: 1px solid {d.separator}; border-radius: 3px;"
        f"  padding: 2px 4px;"
        f"}}"
        f"QSpinBox::up-button, QDoubleSpinBox::up-button,"
        f"QSpinBox::down-button, QDoubleSpinBox::down-button {{"
        f"  background-color: {d.separator};"
        f"  border: none; width: 14px;"
        f"}}"
        f"QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,"
        f"QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{"
        f"  background-color: {d.accent};"
        f"}}"
        f"QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{"
        f"  border-left: 4px solid transparent; border-right: 4px solid transparent;"
        f"  border-bottom: 5px solid {d.text}; width: 0; height: 0;"
        f"}}"
        f"QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{"
        f"  border-left: 4px solid transparent; border-right: 4px solid transparent;"
        f"  border-top: 5px solid {d.text}; width: 0; height: 0;"
        f"}}"
    )


def build_dialog_stylesheet(d: DesignSettings) -> str:
    """ダイアログ向けのダークテーマスタイルシート。

    QDialog に setStyleSheet で適用する。
    QApplication レベルのスタイルを補完し、ダイアログ固有の要素を整える。
    """
    return (
        f"QDialog {{ background-color: {d.panel}; color: {d.text}; }}"
        f"QTabWidget::pane {{ border: 1px solid {d.separator}; background: {d.bg}; }}"
        f"QTabBar::tab {{ background: {d.separator}; color: {d.text}; padding: 6px 12px; }}"
        f"QTabBar::tab:selected {{ background: {d.accent}; }}"
        f"QListWidget {{ background-color: {d.bg}; color: {d.text};"
        f"  border: 1px solid {d.separator}; }}"
        f"QListWidget::item:selected {{ background-color: {d.separator}; }}"
        f"QGroupBox {{ color: {d.text}; border: 1px solid {d.separator};"
        f"  border-radius: 3px; margin-top: 6px; padding-top: 10px; }}"
        f"QGroupBox::title {{ subcontrol-origin: margin; left: 8px; }}"
    )


def get_header_colors(theme_mode: str, design: DesignSettings) -> dict:
    """折りたたみヘッダー用の色セットを返す。

    Returns:
        {"bg_expanded", "bg_collapsed", "text", "hover"} のカラー辞書
    """
    effective = resolve_theme_mode(theme_mode)
    if effective == "light":
        return {
            "bg_expanded": "#d0d0d0",
            "bg_collapsed": "#e8e8e8",
            "text": "#1a1a1a",
            "hover": _LIGHT_ACCENT,
        }
    return {
        "bg_expanded": design.separator,
        "bg_collapsed": design.panel,
        "text": design.text,
        "hover": design.accent,
    }


def build_app_stylesheet(d: DesignSettings) -> str:
    """DesignSettings から QApplication 全体向けスタイルシートを生成する。

    主要ウィジェット型に対してダークテーマの基本配色を設定する。
    個別ウィジェットの setStyleSheet で上書き可能。
    """
    return f"""
/* ── 共通ベース ── */
QWidget {{
    background-color: {d.panel};
    color: {d.text};
    font-family: Meiryo;
}}

/* ── ラベル ── */
QLabel {{
    background-color: transparent;
    color: {d.text};
}}

/* ── ボタン ── */
QPushButton {{
    background-color: {d.separator};
    color: {d.text};
    border: none;
    border-radius: 3px;
    padding: 4px 8px;
}}
QPushButton:hover {{
    background-color: {d.accent};
}}
QPushButton:disabled {{
    background-color: {d.panel};
    color: {d.text_sub};
}}

/* ── チェックボックス ── */
QCheckBox {{
    color: {d.text};
    spacing: 6px;
}}
QCheckBox::indicator {{
    width: 14px;
    height: 14px;
    border: 1px solid {d.text_sub};
    border-radius: 2px;
    background-color: {d.panel};
}}
QCheckBox::indicator:checked {{
    background-color: {d.accent};
    border-color: {d.accent};
}}
QCheckBox::indicator:hover {{
    border-color: {d.text};
}}

/* ── コンボボックス ── */
QComboBox {{
    background-color: {d.separator};
    color: {d.text};
    border: 1px solid {d.separator};
    border-radius: 3px;
    padding: 3px 6px;
}}
QComboBox::drop-down {{
    border: none;
    width: 16px;
}}
QComboBox QAbstractItemView {{
    background-color: {d.panel};
    color: {d.text};
    selection-background-color: {d.separator};
    selection-color: {d.text};
    border: 1px solid {d.separator};
}}

/* ── スピンボックス ── */
QSpinBox, QDoubleSpinBox {{
    background-color: {d.separator};
    color: {d.text};
    border: 1px solid {d.separator};
    border-radius: 3px;
    padding: 2px 4px;
}}
QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    background-color: {d.separator};
    border: none;
    width: 14px;
}}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
    background-color: {d.accent};
}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-bottom: 5px solid {d.text};
    width: 0; height: 0;
}}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {d.text};
    width: 0; height: 0;
}}

/* ── テキスト入力 ── */
QLineEdit {{
    background-color: {d.separator};
    color: {d.text};
    border: 1px solid {d.separator};
    border-radius: 3px;
    padding: 2px 4px;
}}

/* ── スライダー ── */
QSlider::groove:horizontal {{
    background: {d.separator};
    height: 4px;
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {d.accent};
    width: 12px;
    margin: -4px 0;
    border-radius: 6px;
}}

/* ── スクロールエリア ── */
QScrollArea {{
    border: none;
    background-color: {d.panel};
}}
QScrollBar:vertical {{
    width: 6px;
    background: {d.panel};
}}
QScrollBar::handle:vertical {{
    background: {d.separator};
    border-radius: 3px;
}}
QScrollBar:horizontal {{
    height: 6px;
    background: {d.panel};
}}
QScrollBar::handle:horizontal {{
    background: {d.separator};
    border-radius: 3px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    height: 0; width: 0;
}}

/* ── メニュー ── */
QMenu {{
    background-color: {d.panel};
    color: {d.text};
    font-size: 10pt;
    border: 1px solid {d.separator};
}}
QMenu::item:selected {{
    background-color: {d.separator};
}}

/* ── ツールチップ ── */
QToolTip {{
    background-color: {d.separator};
    color: {d.text};
    border: 1px solid {d.text_sub};
    padding: 2px 4px;
}}

/* ── フレーム ── */
QFrame {{
    background-color: {d.panel};
}}
"""


# ── ライトテーマ用カラー定数 ──
_LIGHT_BG = "#f5f5f5"
_LIGHT_PANEL = "#ffffff"
_LIGHT_TEXT = "#1a1a1a"
_LIGHT_TEXT_SUB = "#666666"
_LIGHT_SEPARATOR = "#d0d0d0"
_LIGHT_ACCENT = "#e94560"


def build_light_stylesheet() -> str:
    """ライトテーマ向け QApplication スタイルシートを生成する。"""
    bg = _LIGHT_BG
    panel = _LIGHT_PANEL
    text = _LIGHT_TEXT
    text_sub = _LIGHT_TEXT_SUB
    sep = _LIGHT_SEPARATOR
    accent = _LIGHT_ACCENT
    return f"""
/* ── 共通ベース ── */
QWidget {{
    background-color: {panel};
    color: {text};
    font-family: Meiryo;
}}

QLabel {{
    background-color: transparent;
    color: {text};
}}

QPushButton {{
    background-color: {sep};
    color: {text};
    border: none;
    border-radius: 3px;
    padding: 4px 8px;
}}
QPushButton:hover {{
    background-color: {accent};
    color: white;
}}
QPushButton:disabled {{
    background-color: {bg};
    color: {text_sub};
}}

QCheckBox {{
    color: {text};
    spacing: 6px;
}}
QCheckBox::indicator {{
    width: 14px;
    height: 14px;
    border: 1px solid {text_sub};
    border-radius: 2px;
    background-color: {panel};
}}
QCheckBox::indicator:checked {{
    background-color: {accent};
    border-color: {accent};
}}
QCheckBox::indicator:hover {{
    border-color: {text};
}}

QComboBox {{
    background-color: {panel};
    color: {text};
    border: 1px solid {sep};
    border-radius: 3px;
    padding: 3px 6px;
}}
QComboBox::drop-down {{
    border: none;
    width: 16px;
}}
QComboBox QAbstractItemView {{
    background-color: {panel};
    color: {text};
    selection-background-color: {sep};
    selection-color: {text};
    border: 1px solid {sep};
}}

QSpinBox, QDoubleSpinBox {{
    background-color: {panel};
    color: {text};
    border: 1px solid {sep};
    border-radius: 3px;
    padding: 2px 4px;
}}
QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    background-color: {sep};
    border: none;
    width: 14px;
}}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
    background-color: {accent};
}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-bottom: 5px solid {text};
    width: 0; height: 0;
}}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {text};
    width: 0; height: 0;
}}

QLineEdit {{
    background-color: {panel};
    color: {text};
    border: 1px solid {sep};
    border-radius: 3px;
    padding: 2px 4px;
}}

QSlider::groove:horizontal {{
    background: {sep};
    height: 4px;
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {accent};
    width: 12px;
    margin: -4px 0;
    border-radius: 6px;
}}

QScrollArea {{
    border: none;
    background-color: {bg};
}}
QScrollBar:vertical {{
    width: 6px;
    background: {bg};
}}
QScrollBar::handle:vertical {{
    background: {sep};
    border-radius: 3px;
}}
QScrollBar:horizontal {{
    height: 6px;
    background: {bg};
}}
QScrollBar::handle:horizontal {{
    background: {sep};
    border-radius: 3px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    height: 0; width: 0;
}}

QMenu {{
    background-color: {panel};
    color: {text};
    font-size: 10pt;
    border: 1px solid {sep};
}}
QMenu::item:selected {{
    background-color: {sep};
}}

QToolTip {{
    background-color: {panel};
    color: {text};
    border: 1px solid {sep};
    padding: 2px 4px;
}}

QFrame {{
    background-color: {panel};
}}

QListWidget {{
    background-color: {bg};
    color: {text};
    border: 1px solid {sep};
}}
QListWidget::item:selected {{
    background-color: {sep};
}}

QTabWidget::pane {{
    border: 1px solid {sep};
    background: {bg};
}}
QTabBar::tab {{
    background: {sep};
    color: {text};
    padding: 6px 12px;
}}
QTabBar::tab:selected {{
    background: {accent};
    color: white;
}}

QTextEdit {{
    background-color: {bg};
    color: {text};
    border: 1px solid {sep};
}}
"""


def get_app_stylesheet(theme_mode: str, design: DesignSettings) -> str:
    """テーマモードに応じた QApplication スタイルシートを返す。

    Args:
        theme_mode: "light", "dark", or "system"
        design: dark テーマ時に使用する DesignSettings
    """
    effective = resolve_theme_mode(theme_mode)
    if effective == "light":
        return build_light_stylesheet()
    return build_app_stylesheet(design)
