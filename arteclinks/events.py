"""
ArTec Links ボタンイベントラッパー + デバイス状態管理。

Button の生 PRESS/RELEASE を高レベルなイベントに変換する。
"""

import threading
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from .button import Button
    from .led import LED


# ----------------------------------------------------------------
# 状態管理
# ----------------------------------------------------------------

@dataclass
class DeviceState:
    """
    デバイスの現在状態スナップショット。

    Attributes:
        led_rgb:        現在の LED 色 (r, g, b)。off のとき (0, 0, 0)。
        button_pressed: ボタンが押されているか。
        connected:      デバイスに接続中か。
    """
    led_rgb:        Tuple[int, int, int] = (0, 0, 0)
    button_pressed: bool                 = False
    connected:      bool                 = True


# ----------------------------------------------------------------
# バリデーション
# ----------------------------------------------------------------

def validate_rgb(r: int, g: int, b: int) -> Tuple[int, int, int]:
    """
    RGB 値が 0〜100 の範囲内か検証し、クランプして返す。

    Raises:
        TypeError: 整数以外が渡された場合
    """
    for name, v in (("r", r), ("g", g), ("b", b)):
        if not isinstance(v, (int, float)):
            raise TypeError(f"{name} は数値でなければなりません (got {type(v).__name__})")
    return max(0, min(100, int(r))), max(0, min(100, int(g))), max(0, min(100, int(b)))


def validate_color_name(color: str, valid: dict) -> str:
    """
    色名が有効か検証して返す。

    Raises:
        ValueError: 不明な色名の場合
    """
    if not isinstance(color, str):
        raise TypeError(f"color は文字列でなければなりません (got {type(color).__name__})")
    lower = color.lower()
    if lower not in valid:
        raise ValueError(
            f"不明な色: '{color}'。使用可能: {', '.join(valid.keys())}"
        )
    return lower


# ----------------------------------------------------------------
# イベントラッパー
# ----------------------------------------------------------------

class ButtonEvents:
    """
    Button の生 PRESS/RELEASE を高レベルイベントに変換するラッパー。

    イベント種別:
        click       - 短押し (LONG_PRESS_MS 未満で離す)
        long_press  - 長押し (LONG_PRESS_MS 以上押し続けて離す)
        double_click - DOUBLE_CLICK_MS 以内に 2 回 click

    注意: double_click を検出するため、click イベントは
    DOUBLE_CLICK_MS だけ遅延して発火する。
    double_click が不要なら on_double_click を登録しなければ
    click は即座に発火する (DOUBLE_CLICK_MS 待ちなし)。

    Usage:
        device.button.start_watching()
        events = ButtonEvents(device.button)
        events.on_click(lambda: print("クリック"))
        events.on_long_press(lambda: print("長押し"))
        events.on_double_click(lambda: print("ダブルクリック"))
    """

    LONG_PRESS_MS:   int = 600   # これ以上でlong_press
    DOUBLE_CLICK_MS: int = 350   # この時間内に2回でdouble_click

    def __init__(self, button: "Button"):
        self._button = button
        self._press_time: Optional[float] = None
        self._last_click_time: Optional[float] = None
        self._pending_click_timer: Optional[threading.Timer] = None

        self._click_callbacks:        List[Callable[[], None]] = []
        self._long_press_callbacks:   List[Callable[[], None]] = []
        self._double_click_callbacks: List[Callable[[], None]] = []

        button.on_press(self._on_press)
        button.on_release(self._on_release)

    # ---- コールバック登録 ----

    def on_click(self, callback: Callable[[], None]) -> None:
        """短押しクリックのコールバックを登録する"""
        self._click_callbacks.append(callback)

    def on_long_press(self, callback: Callable[[], None]) -> None:
        """長押しのコールバックを登録する"""
        self._long_press_callbacks.append(callback)

    def on_double_click(self, callback: Callable[[], None]) -> None:
        """ダブルクリックのコールバックを登録する"""
        self._double_click_callbacks.append(callback)

    # ---- 内部 ----

    def _on_press(self) -> None:
        self._press_time = time.monotonic()

    def _on_release(self) -> None:
        if self._press_time is None:
            return
        duration_ms = (time.monotonic() - self._press_time) * 1000
        self._press_time = None

        if duration_ms >= self.LONG_PRESS_MS:
            self._cancel_pending_click()
            self._last_click_time = None
            self._fire(self._long_press_callbacks)
            return

        # short press → click or double_click
        now = time.monotonic()

        # double_click リスナーがなければ即発火
        if not self._double_click_callbacks:
            self._fire(self._click_callbacks)
            return

        if (self._last_click_time is not None
                and (now - self._last_click_time) * 1000 < self.DOUBLE_CLICK_MS):
            self._cancel_pending_click()
            self._last_click_time = None
            self._fire(self._double_click_callbacks)
        else:
            self._last_click_time = now
            self._cancel_pending_click()
            self._pending_click_timer = threading.Timer(
                self.DOUBLE_CLICK_MS / 1000,
                self._fire_pending_click,
            )
            self._pending_click_timer.daemon = True
            self._pending_click_timer.start()

    def _fire_pending_click(self) -> None:
        if self._last_click_time is not None:
            self._last_click_time = None
            self._fire(self._click_callbacks)

    def _cancel_pending_click(self) -> None:
        if self._pending_click_timer is not None:
            self._pending_click_timer.cancel()
            self._pending_click_timer = None

    @staticmethod
    def _fire(callbacks: List[Callable[[], None]]) -> None:
        for cb in callbacks:
            threading.Thread(target=cb, daemon=True).start()
