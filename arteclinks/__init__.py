"""
arteclinks - ArTec Links メインユニット Python ライブラリ

ArTec Links メインユニット (ESP32-C3 + MicroPython) を
USB または BLE で制御するためのホスト側 Python ライブラリ。

Quick start:
    from arteclinks import ArTecLinks

    with ArTecLinks.connect_usb() as device:
        device.led.blue()
        device.button.wait_for_press()
        device.led.green()
"""

from .device import ArTecLinks
from .led import LED, COLORS
from .button import Button
from .events import ButtonEvents, DeviceState, validate_rgb, validate_color_name
from ._repl import ReplError, ConnectionError
from ._ble import BleReplError, BleConnectionError

__version__ = "0.2.0"
__all__ = [
    "ArTecLinks",
    "LED",
    "Button",
    "ButtonEvents",
    "DeviceState",
    "validate_rgb",
    "validate_color_name",
    "COLORS",
    "ReplError",
    "ConnectionError",
    "BleReplError",
    "BleConnectionError",
]
