"""
ArTec Links デバイス メインクラス。

USB または BLE で ArTec Links メインユニットに接続し、
LED・ボタンを操作するための統合インターフェース。
"""

import asyncio
import queue
import threading
from typing import Optional

from ._repl import RawRepl, ReplError, ConnectionError as UsbConnectionError
from ._ble import BleRepl, BleReplError, BleConnectionError
from .led import LED
from .button import Button
from .events import DeviceState, ButtonEvents


class ArTecLinks:
    """
    ArTec Links メインユニットのコントローラ。

    USB接続 (有線) と BLE接続 (無線) の両方をサポートする。
    接続方式に関わらず、led / button のインターフェースは共通。

    USB接続:
        with ArTecLinks.connect_usb() as device:
            device.led.blue()
            device.button.wait_for_press()

    BLE接続:
        with ArTecLinks.connect_ble() as device:
            device.led.green()

    suzume-agent での典型的な使い方:
        device = ArTecLinks.connect_usb()

        # エージェントの状態を LED で表現
        device.led.set_color("blue")    # 待機中
        device.led.set_color("green")   # 話している
        device.led.set_color("yellow")  # 考え中
        device.led.set_color("red")     # エラー
        device.led.off()                # スリープ

        # 人間からのトリガー入力
        device.button.wait_for_press()  # ボタンが押されるまで待つ
        device.button.on_press(callback)  # 非同期で検出
    """

    def __init__(self, repl):
        self._repl = repl
        self._state = DeviceState()
        self.led = LED(self)
        self.button = Button(self)
        self.events = ButtonEvents(self.button)

        # LED コマンドを直列化するワーカー
        # (コールバックスレッドから LED を触っても競合しないようにするキュー)
        self._led_queue: queue.Queue = queue.Queue()
        self._led_worker_thread = threading.Thread(
            target=self._led_worker, daemon=True
        )
        self._led_worker_thread.start()

    # ------------------------------------------------------------------
    # 接続ファクトリ
    # ------------------------------------------------------------------

    @classmethod
    def connect_usb(
        cls,
        port: str = "/dev/cu.usbmodem101",
        baudrate: int = 115200,
        timeout: float = 5.0,
    ) -> "ArTecLinks":
        """
        USB (シリアル) で接続する。

        デバイスは通常モード (ボタンを押さずに) 起動しておくこと。

        Args:
            port: シリアルポート。Mac デフォルト: /dev/cu.usbmodem101
                  Windows の場合: COM3 など
            baudrate: ボーレート (変更不要)
            timeout: タイムアウト秒数

        Returns:
            接続済みの ArTecLinks インスタンス

        Raises:
            ConnectionError: ポートが開けない場合
        """
        repl = RawRepl(port, baudrate, timeout)
        repl.open()
        return cls(repl)

    @classmethod
    def connect_ble(
        cls,
        device_name: Optional[str] = None,
        timeout: float = 10.0,
    ) -> "ArTecLinks":
        """
        BLE (Bluetooth) で接続する。

        デバイスはボタンを押しながら起動しておくこと。
        デバイス名は "AL-XXXX" の形式 (XXXX は MAC アドレス末尾4桁)。

        Args:
            device_name: 接続するデバイス名 (例: "AL-6370")。
                         None の場合、最初に見つかった AL- デバイスに接続。
            timeout: スキャン・接続タイムアウト秒数

        Returns:
            接続済みの ArTecLinks インスタンス

        Raises:
            BleConnectionError: デバイスが見つからない・接続できない場合
        """
        repl = BleRepl(device_name, timeout)
        asyncio.get_event_loop().run_until_complete(repl.open())
        return cls(repl)

    # ------------------------------------------------------------------
    # 内部: コード実行
    # ------------------------------------------------------------------

    def _exec(self, code: str, timeout: Optional[float] = None) -> str:
        """デバイス上でPythonコードを実行して結果を返す (内部用)"""
        if isinstance(self._repl, BleRepl):
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(self._repl.exec(code, timeout))
        return self._repl.exec(code, timeout)

    def _exec_or_stream(self, exec_code: str, stream_cmd: Optional[str] = None) -> None:
        """
        LED コマンドをキューに入れる (内部用)。
        ワーカースレッドが直列に処理するので、コールバックから呼んでも安全。

        Args:
            exec_code:  非ストリームモード時に実行する MicroPython コード
            stream_cmd: ストリームモード時にデバイス stdin へ送るコマンド行 (末尾 \\n 含む)
                        None の場合はストリームモードでも pause/resume して exec_code を実行
        """
        self._led_queue.put((exec_code, stream_cmd))

    def _led_worker(self) -> None:
        """LED コマンドキューを直列処理するワーカー (バックグラウンドスレッド)"""
        from .button import _MONITOR_SCRIPT
        while True:
            item = self._led_queue.get()
            if item is None:
                break
            exec_code, stream_cmd = item
            try:
                with self._repl._lock:
                    if self._repl._stream_mode and stream_cmd is not None:
                        # ストリームを止めずに stdin 経由でコマンド送信
                        self._repl.write_stream(stream_cmd.encode())
                    elif self._repl._stream_mode:
                        # stream_cmd がない場合は従来通り pause/resume
                        self._repl.pause_stream()
                        self._repl.exec(exec_code)
                        self._repl.resume_stream(_MONITOR_SCRIPT)
                    else:
                        self._repl.exec(exec_code)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # 接続管理
    # ------------------------------------------------------------------

    @property
    def state(self) -> DeviceState:
        """現在のデバイス状態スナップショットを返す"""
        self._state.connected = self.is_connected()
        return self._state

    def disconnect(self) -> None:
        """デバイスとの接続を切断する"""
        self._led_queue.put(None)  # ワーカー停止
        self.button.stop_watching()
        self._state.connected = False
        if isinstance(self._repl, BleRepl):
            loop = asyncio.get_event_loop()
            loop.run_until_complete(self._repl.close())
        else:
            self._repl.close()

    def is_connected(self) -> bool:
        """接続中かどうかを返す"""
        if isinstance(self._repl, BleRepl):
            return self._repl._client is not None and self._repl._client.is_connected
        return self._repl._serial is not None and self._repl._serial.is_open

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.disconnect()

    def __repr__(self) -> str:
        mode = "BLE" if isinstance(self._repl, BleRepl) else "USB"
        status = "接続中" if self.is_connected() else "切断"
        return f"<ArTecLinks {mode} {status}>"
