"""
UR10 WebSocket Communication Module

This module provides WebSocket-based communication interfaces for Universal Robots UR10.
Based on the official UR Socket Communication documentation.

Author: jsecco ®
"""

from .websocket_controller import WebSocketController
from .websocket_receiver import WebSocketReceiver
from .dashboard_client import DashboardClient

__all__ = ['WebSocketController', 'WebSocketReceiver', 'DashboardClient']
