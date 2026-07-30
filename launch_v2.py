"""launch_v2.py - Launcher for the v2 redesigned UI (production entry).

Shows MainWindowV2 fullscreen on the Elo i3 touchscreen. The desktop icon
(launch.sh) runs this. Escape closes it. To revert to the professional UI,
use git history (tag pre-cleanup-20260730).

Author: jsecco (R)
"""
import logging
import sys

# Log to a file AND stderr so the running app's behaviour is observable
# (safety polling, dashboard connect, fault detection, recovery commands).
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("/tmp/v2_debug.log"),
        logging.StreamHandler(sys.stderr),
    ],
)

sys.path.insert(0, "src")

import yaml
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QShortcut, QKeySequence
from PyQt6.QtCore import Qt

cfg = yaml.safe_load(open("config/robot_config.yaml"))

app = QApplication(sys.argv)
try:
    from ui.theme_v2 import WINDOW_QSS
    app.setStyleSheet(WINDOW_QSS)
except Exception as exc:
    logging.getLogger("launch_v2").warning("WINDOW_QSS not applied: %s", exc)

from ui.main_window_v2 import MainWindowV2

win = MainWindowV2(cfg)
QShortcut(QKeySequence(Qt.Key.Key_Escape), win, activated=app.quit)
win.showFullScreen()
logging.getLogger("launch_v2").info("v2 window shown (production launcher)")

run_loop = getattr(app, "exec")
sys.exit(run_loop())
