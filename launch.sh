#!/bin/bash
# UR10 Jog Control - Desktop Launcher
# Author: jsecco (R)
#
# Launches the v2 redesigned UI (recovery, redesigned settings + keypad,
# light/dark themes, color-coded jog axes). To revert to the professional
# UI, use git history (tag pre-cleanup-20260730).

cd /home/ur10/Documents/i3UR10
exec /home/ur10/Documents/i3UR10/venv/bin/python /home/ur10/Documents/i3UR10/launch_v2.py "$@"
