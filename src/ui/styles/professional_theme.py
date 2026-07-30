"""
Professional Theme System for UR10 Robot Control Interface

This module provides a clean, modern, professional styling system
designed to match high-end industrial control interfaces.

Author: jsecco ®
"""

from pathlib import Path

# Paths to spinbox +/- icons (project root: src/ui/styles -> 4 levels up to repo root)
_ASSETS_ICONS = Path(__file__).resolve().parent.parent.parent.parent / "assets" / "icons"
# file:// not required; absolute path works in Qt QSS
_SPINBOX_PLUS_ICON = (_ASSETS_ICONS / "spinbox-plus.svg").as_posix()
_SPINBOX_MINUS_ICON = (_ASSETS_ICONS / "spinbox-minus.svg").as_posix()


class ProfessionalColors:
    """Professional color palette for industrial control interfaces."""

    # Primary colors - Clean blue theme
    PRIMARY_BLUE = '#2196F3'
    PRIMARY_BLUE_DARK = '#1976D2'
    PRIMARY_BLUE_LIGHT = '#64B5F6'

    # Background colors
    BACKGROUND_MAIN = '#F8F9FA'
    BACKGROUND_CARD = '#FFFFFF'
    BACKGROUND_SECONDARY = '#F5F5F5'

    # Status colors
    SUCCESS_GREEN = '#4CAF50'
    WARNING_ORANGE = '#FF9800'
    ERROR_RED = '#F44336'
    INFO_BLUE = '#2196F3'

    # Text colors
    TEXT_PRIMARY = '#212529'
    TEXT_SECONDARY = '#6C757D'
    TEXT_LIGHT = '#ADB5BD'
    TEXT_WHITE = '#FFFFFF'

    # Border colors
    BORDER_LIGHT = '#DEE2E6'
    BORDER_MEDIUM = '#CED4DA'
    BORDER_DARK = '#ADB5BD'

    # Shadow colors
    SHADOW_LIGHT = 'rgba(0, 0, 0, 0.08)'
    SHADOW_MEDIUM = 'rgba(0, 0, 0, 0.12)'
    SHADOW_STRONG = 'rgba(0, 0, 0, 0.16)'


def create_professional_stylesheet():
    """Create the main professional stylesheet for the application."""
    return f"""
    /* Main Window */
    QMainWindow {{
        background-color: {ProfessionalColors.BACKGROUND_MAIN};
        font-family: 'Segoe UI', 'SF Pro Display', -apple-system, system-ui, sans-serif;
    }}

    /* Group Boxes - Card Style */
    QGroupBox {{
        background-color: {ProfessionalColors.BACKGROUND_CARD};
        border: 1px solid {ProfessionalColors.BORDER_LIGHT};
        border-radius: 12px;
        margin: 8px;
        padding: 16px;
        font-weight: 600;
        font-size: 14px;
        color: {ProfessionalColors.TEXT_PRIMARY};
    }}

    QGroupBox::title {{
        subcontrol-origin: margin;
        subcontrol-position: top left;
        padding: 0 8px;
        margin-left: 8px;
        color: {ProfessionalColors.PRIMARY_BLUE};
        font-weight: 700;
    }}

    /* Primary Buttons */
    QPushButton {{
        background-color: {ProfessionalColors.PRIMARY_BLUE};
        border: none;
        border-radius: 8px;
        color: {ProfessionalColors.TEXT_WHITE};
        font-weight: 600;
        font-size: 14px;
        min-height: 36px;
        padding: 12px 24px;
        margin: 4px;
    }}

    QPushButton:hover {{
        background-color: {ProfessionalColors.PRIMARY_BLUE_DARK};
    }}

    QPushButton:pressed {{
        background-color: {ProfessionalColors.PRIMARY_BLUE_DARK};
    }}

    QPushButton:disabled {{
        background-color: {ProfessionalColors.BORDER_MEDIUM};
        color: {ProfessionalColors.TEXT_LIGHT};
    }}

    /* Jog Control Buttons */
    QPushButton#jogButton {{
        background-color: {ProfessionalColors.PRIMARY_BLUE};
        min-width: 70px;
        min-height: 60px;
        font-size: 14px;
        font-weight: 700;
        border-radius: 12px;
    }}

    QPushButton#jogButton:hover {{
        background-color: {ProfessionalColors.PRIMARY_BLUE_DARK};
    }}

    QPushButton#jogButton:pressed {{
        background-color: {ProfessionalColors.PRIMARY_BLUE_DARK};
        border: 3px solid {ProfessionalColors.PRIMARY_BLUE_LIGHT};
    }}

    /* Emergency Button */
    QPushButton#emergencyButton {{
        background-color: {ProfessionalColors.ERROR_RED};
        min-width: 140px;
        min-height: 70px;
        font-size: 16px;
        font-weight: 800;
        border-radius: 16px;
        color: {ProfessionalColors.TEXT_WHITE};
    }}

    QPushButton#emergencyButton:hover {{
        background-color: #D32F2F;
    }}

    QPushButton#emergencyButton:pressed {{
        background-color: #C62828;
    }}

    /* Connect Button (Green) */
    QPushButton#connectButton {{
        background-color: {ProfessionalColors.SUCCESS_GREEN};
        min-height: 40px;
        font-size: 14px;
        font-weight: 600;
    }}

    QPushButton#connectButton:hover {{
        background-color: #45a049;
    }}

    /* Disconnect Button (Red) */
    QPushButton#disconnectButton {{
        background-color: {ProfessionalColors.ERROR_RED};
        min-height: 40px;
        font-size: 14px;
        font-weight: 600;
    }}

    QPushButton#disconnectButton:hover {{
        background-color: #d32f2f;
    }}

    /* Secondary Buttons */
    QPushButton#secondaryButton {{
        background-color: {ProfessionalColors.BACKGROUND_SECONDARY};
        color: {ProfessionalColors.TEXT_PRIMARY};
        border: 2px solid {ProfessionalColors.BORDER_LIGHT};
    }}

    QPushButton#secondaryButton:hover {{
        background-color: {ProfessionalColors.BORDER_LIGHT};
        border-color: {ProfessionalColors.BORDER_MEDIUM};
    }}

    /* Tab Widget */
    QTabWidget::pane {{
        border: 1px solid {ProfessionalColors.BORDER_LIGHT};
        border-radius: 8px;
        background-color: {ProfessionalColors.BACKGROUND_CARD};
    }}

    QTabBar::tab {{
        background-color: {ProfessionalColors.BACKGROUND_SECONDARY};
        border: 1px solid {ProfessionalColors.BORDER_LIGHT};
        padding: 12px 24px;
        margin: 2px;
        border-radius: 8px 8px 0 0;
        font-weight: 600;
    }}

    QTabBar::tab:selected {{
        background-color: {ProfessionalColors.PRIMARY_BLUE};
        color: {ProfessionalColors.TEXT_WHITE};
        border-color: {ProfessionalColors.PRIMARY_BLUE};
    }}

    QTabBar::tab:hover:!selected {{
        background-color: {ProfessionalColors.PRIMARY_BLUE_LIGHT};
        color: {ProfessionalColors.TEXT_WHITE};
    }}

    /* Labels */
    QLabel {{
        color: {ProfessionalColors.TEXT_PRIMARY};
        font-size: 14px;
    }}

    QLabel#titleLabel {{
        color: {ProfessionalColors.PRIMARY_BLUE};
        font-size: 14px;
        font-weight: 700;
        margin-bottom: 8px;
    }}

    QLabel#valueLabel {{
        font-family: 'SF Mono', 'Fira Code', 'Roboto Mono', monospace;
        font-size: 14px;
        font-weight: 600;
        color: {ProfessionalColors.SUCCESS_GREEN};
        background-color: {ProfessionalColors.BACKGROUND_SECONDARY};
        padding: 8px 12px;
        border-radius: 6px;
        border: 1px solid {ProfessionalColors.BORDER_LIGHT};
    }}

    /* Position panel (TCP / Joint angles) - compact, uniform */
    QGroupBox#positionPanelGroup {{
        font-size: 13px;
        font-weight: 600;
    }}
    QGroupBox#positionPanelGroup::title {{
        font-size: 13px;
    }}
    QLabel#positionPanelLabel {{
        font-size: 13px;
        color: {ProfessionalColors.TEXT_SECONDARY};
        font-weight: 500;
    }}

    QLabel#statusLabel {{
        font-weight: 600;
        padding: 6px 12px;
        border-radius: 6px;
    }}

    QLabel#statusConnected {{
        background-color: {ProfessionalColors.SUCCESS_GREEN};
        color: {ProfessionalColors.TEXT_WHITE};
    }}

    QLabel#statusDisconnected {{
        background-color: {ProfessionalColors.ERROR_RED};
        color: {ProfessionalColors.TEXT_WHITE};
    }}

    /* Slider */
    QSlider::groove:horizontal {{
        border: 1px solid {ProfessionalColors.BORDER_MEDIUM};
        height: 8px;
        background-color: {ProfessionalColors.BACKGROUND_SECONDARY};
        border-radius: 4px;
    }}

    QSlider::handle:horizontal {{
        background-color: {ProfessionalColors.PRIMARY_BLUE};
        border: 2px solid {ProfessionalColors.TEXT_WHITE};
        width: 20px;
        height: 20px;
        border-radius: 12px;
        margin: -8px 0;
    }}

    QSlider::handle:horizontal:hover {{
        background-color: {ProfessionalColors.PRIMARY_BLUE_DARK};
    }}

    /* Text Edit - Logs */
    QTextEdit {{
        background-color: {ProfessionalColors.BACKGROUND_CARD};
        border: 1px solid {ProfessionalColors.BORDER_LIGHT};
        border-radius: 8px;
        padding: 12px;
        font-family: 'SF Mono', 'Fira Code', 'Roboto Mono', monospace;
        font-size: 12px;
        color: {ProfessionalColors.TEXT_SECONDARY};
    }}

    /* Scroll Areas */
    QScrollArea {{
        background-color: transparent;
        border: none;
    }}

    QScrollBar:vertical {{
        background-color: {ProfessionalColors.BACKGROUND_SECONDARY};
        border: none;
        border-radius: 6px;
        width: 12px;
    }}

    QScrollBar::handle:vertical {{
        background-color: {ProfessionalColors.BORDER_MEDIUM};
        border-radius: 6px;
        min-height: 24px;
    }}

    QScrollBar::handle:vertical:hover {{
        background-color: {ProfessionalColors.BORDER_DARK};
    }}

    /* SpinBox / DoubleSpinBox - large touch-friendly up/down buttons (not the text box)
       To change arrow button size: edit width (default 48px) and min-height (default 28px) below.
       Up button shows +, down button shows - for visibility. */
    QSpinBox::up-button, QDoubleSpinBox::up-button {{
        subcontrol-origin: border;
        subcontrol-position: top right;
        width: 48px;
        min-height: 28px;
        border-left: 1px solid {ProfessionalColors.BORDER_LIGHT};
        border-top-right-radius: 6px;
        background-color: {ProfessionalColors.BACKGROUND_SECONDARY};
    }}

    QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
        image: url("{_SPINBOX_PLUS_ICON}");
        width: 22px;
        height: 22px;
    }}

    QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover {{
        background-color: {ProfessionalColors.BORDER_LIGHT};
    }}

    QSpinBox::up-button:pressed, QDoubleSpinBox::up-button:pressed {{
        background-color: {ProfessionalColors.BORDER_MEDIUM};
    }}

    QSpinBox::down-button, QDoubleSpinBox::down-button {{
        subcontrol-origin: border;
        subcontrol-position: bottom right;
        width: 48px;
        min-height: 28px;
        border-left: 1px solid {ProfessionalColors.BORDER_LIGHT};
        border-bottom-right-radius: 6px;
        background-color: {ProfessionalColors.BACKGROUND_SECONDARY};
    }}

    QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
        image: url("{_SPINBOX_MINUS_ICON}");
        width: 22px;
        height: 22px;
    }}

    QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
        background-color: {ProfessionalColors.BORDER_LIGHT};
    }}

    QSpinBox::down-button:pressed, QDoubleSpinBox::down-button:pressed {{
        background-color: {ProfessionalColors.BORDER_MEDIUM};
    }}

    /* Reserve space for the button strip so the number doesn't overlap */
    QSpinBox, QDoubleSpinBox {{
        padding-right: 50px;
    }}
    """


def create_jog_mode_buttons_style():
    """Create style for jog mode toggle buttons."""
    return f"""
    QPushButton#jogModeButton {{
        background-color: {ProfessionalColors.BACKGROUND_SECONDARY};
        color: {ProfessionalColors.TEXT_PRIMARY};
        border: 2px solid {ProfessionalColors.BORDER_LIGHT};
        border-radius: 8px;
        font-weight: 600;
        font-size: 14px;
        min-height: 36px;
        padding: 12px 24px;
        margin: 2px;
    }}

    QPushButton#jogModeButton:checked {{
        background-color: {ProfessionalColors.PRIMARY_BLUE};
        color: {ProfessionalColors.TEXT_WHITE};
        border-color: {ProfessionalColors.PRIMARY_BLUE_DARK};
    }}

    QPushButton#jogModeButton:hover:!checked {{
        background-color: {ProfessionalColors.BORDER_LIGHT};
        border-color: {ProfessionalColors.BORDER_MEDIUM};
    }}
    """


def create_connection_status_style():
    """Create style for connection status indicators."""
    return f"""
    QLabel#connectionIP {{
        color: {ProfessionalColors.SUCCESS_GREEN};
        font-weight: 700;
        font-size: 14px;
        font-family: 'SF Mono', 'Fira Code', 'Roboto Mono', monospace;
    }}

    QLabel#connectionStatus {{
        color: {ProfessionalColors.SUCCESS_GREEN};
        font-weight: 600;
        font-size: 14px;
    }}
    """