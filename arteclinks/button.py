"""
ArTec Links メインユニット ボタン制御。

IRQ ベースの push 方式でボタンイベントを検出する。
デバイス側にモニタースクリプトを送り込み、変化があったときだけ
"PRESS" / "RELEASE" を送ってもらう。ポーリング不要。
"""

import threading
import time
from typing import Callable, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .device import ArTecLinks

# デバイス上で動くモニタースクリプト
# - Pin 3 の変化を IRQ で即座に検出してフラグを立てる
# - メインループ (10ms) でフラグを確認して "PRESS" / "RELEASE" を出力
# - select.poll() で stdin を非ブロッキングに読み、LED コマンドを処理する
#   LED点灯: "Lr,g,b\n" (例: "L100,0,50\n")
#   LED消灯: "O\n"
_MONITOR_SCRIPT = (
    "from machine import Pin\n"
    "import select,sys,time\n"
    "_p=Pin(3,Pin.IN)\n"
    "_f=False\n"
    "_fv=_p.value()\n"
    "_buf=''\n"
    "_sp=select.poll()\n"
    "_sp.register(sys.stdin,select.POLLIN)\n"
    "def _irq(p):\n"
    " global _f,_fv\n"
    " _fv=p.value()\n"
    " _f=True\n"
    "_p.irq(trigger=Pin.IRQ_FALLING|Pin.IRQ_RISING,handler=_irq)\n"
    "while True:\n"
    " if _f:\n"
    "  _f=False\n"
    "  print('PRESS' if _fv==0 else 'RELEASE')\n"
    " if _sp.poll(0):\n"
    "  c=sys.stdin.read(1)\n"
    "  if c==chr(10):\n"
    "   ln=_buf.strip()\n"
    "   _buf=''\n"
    "   if ln and ln[0]=='L':\n"
    "    p=ln[1:].split(',')\n"
    "    from al.hub import led as _l\n"
    "    _l.on(int(p[0]),int(p[1]),int(p[2]))\n"
    "   elif ln=='O':\n"
    "    from al.hub import led as _l;_l.off()\n"
    "  else:\n"
    "   _buf+=c\n"
    " time.sleep_ms(10)"
)


class Button:
    """
    ArTec Links メインユニットのボタンを制御するクラス。

    start_watching() でデバイス側にモニタースクリプトを送り込み、
    ボタン変化を push で受け取る。

    ボタンは active low (押すと 0)。

    Usage:
        device = ArTecLinks.connect_usb()

        # push 方式で監視
        device.button.start_watching()
        device.button.on_press(lambda: print("押された！"))
        device.button.on_release(lambda: print("離された"))

        # ブロッキングで待機
        device.button.wait_for_press()

        # 停止
        device.button.stop_watching()

    LLM エージェントとの連携例:
        device.button.start_watching()
        device.events.on_click(agent.run)
        device.events.on_long_press(agent.stop)
    """

    def __init__(self, device: "ArTecLinks"):
        self._device = device
        self._watching = False
        self._press_callbacks:   List[Callable[[], None]] = []
        self._release_callbacks: List[Callable[[], None]] = []
        self._press_event = threading.Event()

    # ----------------------------------------------------------------
    # 監視
    # ----------------------------------------------------------------

    def start_watching(self) -> None:
        """
        デバイス側にモニタースクリプトを送り込み、push 監視を開始する。

        USB接続: while ループスクリプトをデバイスに送り込む
        BLE接続: デバイス側でバックグラウンドスレッドを起動する
        どちらも repl.monitor_script / repl.exec_stream で透過的に扱う。
        """
        if self._watching:
            return
        self._watching = True
        with self._device._repl._lock:
            self._device._repl.exec_stream(
                self._device._repl.monitor_script, self._on_line
            )

    def stop_watching(self) -> None:
        """ボタン監視を停止する"""
        if not self._watching:
            return
        self._watching = False
        with self._device._repl._lock:
            self._device._repl.stop_stream()

    # ----------------------------------------------------------------
    # コールバック登録
    # ----------------------------------------------------------------

    def on_press(self, callback: Callable[[], None]) -> None:
        """ボタンが押されたときに呼ばれるコールバックを登録する"""
        self._press_callbacks.append(callback)

    def on_release(self, callback: Callable[[], None]) -> None:
        """ボタンが離されたときに呼ばれるコールバックを登録する"""
        self._release_callbacks.append(callback)

    # ----------------------------------------------------------------
    # ブロッキング待機
    # ----------------------------------------------------------------

    def wait_for_press(self, timeout: Optional[float] = None) -> bool:
        """
        ボタンが押されるまでブロッキングで待機する。

        Args:
            timeout: タイムアウト秒数。None で無制限に待機。

        Returns:
            True: 押された / False: タイムアウト
        """
        if not self._watching:
            self.start_watching()

        self._press_event.clear()
        return self._press_event.wait(timeout=timeout)

    # ----------------------------------------------------------------
    # 単発読み取り (監視中でない場合のみ)
    # ----------------------------------------------------------------

    def read(self) -> int:
        """
        ボタンの現在値を返す (監視していないときに使用)。

        Returns:
            0: 押されている / 1: 離されている
        """
        result = self._device._exec(
            "from al.hub import button; print(button.get_value())"
        )
        return int(result.strip())

    def is_pressed(self) -> bool:
        """ボタンが現在押されているか返す (監視していないときに使用)"""
        return self.read() == 0

    # ----------------------------------------------------------------
    # 内部
    # ----------------------------------------------------------------

    def _on_line(self, line: str) -> None:
        if line == 'PRESS':
            self._device._state.button_pressed = True
            self._press_event.set()
            for cb in self._press_callbacks:
                threading.Thread(target=cb, daemon=True).start()
        elif line == 'RELEASE':
            self._device._state.button_pressed = False
            self._press_event.clear()
            for cb in self._release_callbacks:
                threading.Thread(target=cb, daemon=True).start()
