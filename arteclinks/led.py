"""
ArTec Links メインユニット LED 制御。

メインユニット中央の NeoPixel (WS2812B) RGB LED を制御する。
色は 0〜100 のパーセント値で指定する。
"""

from typing import TYPE_CHECKING

from .events import validate_rgb, validate_color_name

if TYPE_CHECKING:
    from .device import ArTecLinks


# よく使う色のプリセット (r, g, b) 0〜100
COLORS = {
    "red":     (100, 0,   0),
    "green":   (0,   100, 0),
    "blue":    (0,   0,   100),
    "white":   (100, 100, 100),
    "yellow":  (100, 100, 0),
    "cyan":    (0,   100, 100),
    "magenta": (100, 0,   100),
    "orange":  (100, 40,  0),
    "purple":  (50,  0,   100),
    "pink":    (100, 20,  60),
    "off":     (0,   0,   0),
}


class LED:
    """
    ArTec Links メインユニットの RGB LED を制御するクラス。

    Usage (USB):
        device = ArTecLinks.connect_usb()
        device.led.set(100, 0, 0)   # 赤
        device.led.blue()           # 青
        device.led.off()            # 消灯

    suzume-agent での使用例:
        # エージェントが「考え中」を示す
        device.led.set_color("blue")
        # エージェントが応答完了を示す
        device.led.set_color("green")
        # エラー状態を示す
        device.led.set_color("red")
    """

    def __init__(self, device: "ArTecLinks"):
        self._device = device

    def set(self, r: int, g: int, b: int) -> None:
        """
        RGB 値で LED を点灯する。

        Args:
            r: 赤 (0〜100)
            g: 緑 (0〜100)
            b: 青 (0〜100)

        Raises:
            TypeError:  数値以外が渡された場合
        """
        r, g, b = validate_rgb(r, g, b)
        self._device._state.led_rgb = (r, g, b)
        self._device._exec_or_stream(
            f"from al.hub import led; led.on({r},{g},{b})",
            f"L{r},{g},{b}\n",
        )

    def set_color(self, color: str) -> None:
        """
        色名で LED を点灯する。

        Args:
            color: 色名。使用可能: red, green, blue, white, yellow,
                   cyan, magenta, orange, purple, pink, off

        Raises:
            TypeError:  文字列以外が渡された場合
            ValueError: 不明な色名の場合
        """
        color = validate_color_name(color, COLORS)
        r, g, b = COLORS[color]
        self.set(r, g, b)

    def off(self) -> None:
        """LED を消灯する"""
        self._device._state.led_rgb = (0, 0, 0)
        self._device._exec_or_stream(
            "from al.hub import led; led.off()",
            "O\n",
        )

    # --- 色名ショートカット ---

    def red(self, brightness: int = 100) -> None:
        """赤で点灯"""
        self.set(brightness, 0, 0)

    def green(self, brightness: int = 100) -> None:
        """緑で点灯"""
        self.set(0, brightness, 0)

    def blue(self, brightness: int = 100) -> None:
        """青で点灯"""
        self.set(0, 0, brightness)

    def white(self, brightness: int = 100) -> None:
        """白で点灯"""
        self.set(brightness, brightness, brightness)

    def yellow(self, brightness: int = 100) -> None:
        """黄で点灯"""
        self.set(brightness, brightness, 0)

    def cyan(self, brightness: int = 100) -> None:
        """シアンで点灯"""
        self.set(0, brightness, brightness)

    def magenta(self, brightness: int = 100) -> None:
        """マゼンタで点灯"""
        self.set(brightness, 0, brightness)

    def orange(self, brightness: int = 100) -> None:
        """オレンジで点灯"""
        self.set(brightness, int(brightness * 0.4), 0)

    def purple(self, brightness: int = 100) -> None:
        """紫で点灯"""
        self.set(int(brightness * 0.5), 0, brightness)


