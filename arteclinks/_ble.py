"""
ArTec Links BLE 通信層。

デバイスが BLE モード (起動時にボタンを押す) で動作しているときに使用する。
内部プロトコルは UART-over-BLE:
  - ホスト→デバイス: RX characteristic に b'\\x01' + code + b'\\x04' を write
  - デバイス→ホスト: TX characteristic の notify で受信、b'OK\\x04\\x04>' で終端

asyncio のイベントループをバックグラウンドスレッドで常時動かすことで、
exec 待機中以外でも BLE 通知 (ボタンイベント等) を受け取れる。

RawRepl (USB) と同じインターフェースを実装しているため、
呼び出し側は接続方式を意識する必要がない。
"""

import asyncio
import threading
from typing import Optional, Callable
from bleak import BleakClient, BleakScanner

# ArTec Links 固有の BLE UUID
SERVICE_UUID   = "AA560001-D2DF-D208-BC74-66D186385587"
TX_CHAR_UUID   = "AA560003-D2DF-D208-BC74-66D186385587"  # デバイス→ホスト (notify)
RX_CHAR_UUID   = "AA560002-D2DF-D208-BC74-66D186385587"  # ホスト→デバイス (write)

DEVICE_PREFIX  = "AL-"
END_MARKER     = b'OK\x04\x04>'

# ボタン監視スクリプト (BLE版)
# USBと異なり、デバイス側スレッドが blerepl.send_data() で直接BLE通知を送る。
# exec() と独立して動作するため pause/resume が不要。
_MONITOR_SCRIPT_BLE = (
    "import _thread,time,blerepl as _br\n"
    "from machine import Pin\n"
    "_br._btn_stop=False\n"
    "def _monitor():\n"
    " _p=Pin(3,Pin.IN)\n"
    " _f=[False,_p.value()]\n"
    " def _irq(p):\n"
    "  _f[1]=p.value()\n"
    "  _f[0]=True\n"
    " _p.irq(trigger=Pin.IRQ_FALLING|Pin.IRQ_RISING,handler=_irq)\n"
    " while not _br._btn_stop:\n"
    "  if _f[0]:\n"
    "   _f[0]=False\n"
    "   _br.send_data(list(b'PRESS\\n' if _f[1]==0 else b'RELEASE\\n'))\n"
    "  time.sleep_ms(10)\n"
    "_thread.start_new_thread(_monitor,())\n"
)

_MONITOR_STOP_BLE = "import blerepl as _br; _br._btn_stop = True"


class BleReplError(Exception):
    """BLE REPL 実行エラー"""
    pass


class BleConnectionError(Exception):
    """BLE 接続エラー"""
    pass


class BleRepl:
    """
    ArTec Links BLE REPL クライアント。

    RawRepl (USB) と同じインターフェースを持ち、上位レイヤーから
    接続方式の違いを隠蔽する。

    asyncio ループをバックグラウンドスレッドで常時稼働させ、
    exec 外でも BLE 通知 (ボタンイベント等) を受信できる。

    追加インターフェース (RawRepl 互換):
        exec_stream(code, on_line) : ボタン監視スレッドをデバイス側で起動
        stop_stream()              : デバイス側スレッドを停止
        pause_stream()             : no-op (BLEはexecと独立)
        resume_stream(script)      : no-op (BLEはexecと独立)
        write_stream(data)         : no-op (BLEはstdinを使わない)
        supports_stream_write      : False
        monitor_script             : BLE用ボタン監視スクリプト
    """

    supports_stream_write: bool = False

    def __init__(self, device_name: Optional[str] = None, timeout: float = 10.0):
        """
        Args:
            device_name: 接続するデバイス名 (例: "AL-6370")。
                         None の場合、最初に見つかった AL- デバイスに接続する。
            timeout: スキャン・接続タイムアウト秒数
        """
        self.device_name = device_name
        self.timeout = timeout
        self._client: Optional[BleakClient] = None
        self._recv_buf = b''
        self._recv_event: Optional[asyncio.Event] = None

        # RawRepl 互換インターフェース
        self._lock = threading.Lock()
        self._stream_mode: bool = False
        self._stream_handler: Optional[Callable[[str], None]] = None

        # BLE 通知を常時受け取るためにイベントループを専用スレッドで常時稼働
        self._loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(
            target=self._run_loop, daemon=True, name='BleRepl-loop'
        )
        self._loop_thread.start()

    def _run_loop(self) -> None:
        """バックグラウンドスレッドでイベントループを常時稼働させる"""
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _submit(self, coro, timeout: Optional[float] = None):
        """コルーチンをBLEループに投入して結果を同期的に受け取る"""
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        t = (timeout or self.timeout) + 5
        return future.result(timeout=t)

    # ------------------------------------------------------------------
    # 同期ラッパー (上位レイヤーから呼ぶ用)
    # ------------------------------------------------------------------

    def open_sync(self) -> None:
        """BLE デバイスをスキャンして接続する (同期版)"""
        self._submit(self.open(), self.timeout)

    def exec_sync(self, code: str, timeout: Optional[float] = None) -> str:
        """Python コードをデバイス上で実行して結果を返す (同期版)"""
        return self._submit(self.exec(code, timeout), timeout)

    def close_sync(self) -> None:
        """BLE 接続を切断して、イベントループを停止する (同期版)"""
        self._submit(self.close())
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._loop_thread.join(timeout=3)

    # ------------------------------------------------------------------
    # 非同期コア
    # ------------------------------------------------------------------

    async def open(self) -> None:
        """BLE デバイスをスキャンして接続する"""
        self._recv_event = asyncio.Event()
        device = await self._scan()
        self._client = BleakClient(device.address)
        await self._client.connect(timeout=self.timeout)
        await self._client.start_notify(TX_CHAR_UUID, self._on_notify)

    async def close(self) -> None:
        """BLE 接続を切断する"""
        if self._client and self._client.is_connected:
            try:
                await self._client.stop_notify(TX_CHAR_UUID)
            except Exception:
                pass
            await self._client.disconnect()
        self._client = None

    async def exec(self, code: str, timeout: Optional[float] = None) -> str:
        """
        Python コードをデバイス上で実行し、標準出力を返す。

        Raises:
            BleReplError: 実行エラー
            BleConnectionError: 接続が切れている場合
        """
        if not self._client or not self._client.is_connected:
            raise BleConnectionError("BLE デバイスに接続されていません")

        t = timeout or self.timeout
        self._recv_buf = b''
        self._recv_event.clear()

        payload = b'\x01' + code.encode() + b'\x04'
        await self._client.write_gatt_char(RX_CHAR_UUID, payload)

        try:
            await asyncio.wait_for(self._recv_event.wait(), timeout=t)
        except asyncio.TimeoutError:
            raise BleConnectionError("BLE 応答タイムアウト")

        raw = self._recv_buf
        if raw.endswith(END_MARKER):
            raw = raw[: -len(END_MARKER)]

        decoded = raw.decode(errors='replace')
        if 'Traceback' in decoded or 'Error' in decoded:
            raise BleReplError(decoded.strip())

        return decoded

    @property
    def is_connected(self) -> bool:
        return self._client is not None and self._client.is_connected

    # ------------------------------------------------------------------
    # RawRepl 互換: ストリームインターフェース
    # ------------------------------------------------------------------

    def exec_stream(self, code: str, on_line: Callable[[str], None]) -> None:
        """
        ボタン監視を開始する。

        デバイス側でスレッドを起動し、ボタン変化を send_data() で通知させる。
        USB版と異なり exec() と完全に独立して動作する。
        """
        self._stream_handler = on_line
        self._stream_mode = True
        self.exec_sync(code)

    def stop_stream(self) -> None:
        """ボタン監視を停止する"""
        if not self._stream_mode:
            return
        self._stream_mode = False
        self._stream_handler = None
        try:
            self.exec_sync(_MONITOR_STOP_BLE)
        except Exception:
            pass

    def pause_stream(self) -> None:
        """no-op: BLEではexecとボタン監視スレッドが独立しているため不要"""
        pass

    def resume_stream(self, script: str) -> None:
        """no-op: BLEではexecとボタン監視スレッドが独立しているため不要"""
        pass

    def write_stream(self, data: bytes) -> None:
        """no-op: BLEではデバイスstdinを使わない"""
        pass

    @property
    def monitor_script(self) -> str:
        """BLE用ボタン監視スクリプト"""
        return _MONITOR_SCRIPT_BLE

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _on_notify(self, sender, data: bytes) -> None:
        """BLE TX notify コールバック (ループスレッドから呼ばれる)"""
        # ストリームモード中に END_MARKER なしで届いた通知 → ボタンイベント
        if self._stream_mode and self._stream_handler and END_MARKER not in data:
            decoded = data.decode(errors='replace')
            for line in decoded.split('\n'):
                line = line.strip()
                if line:
                    self._stream_handler(line)
            return

        # exec レスポンス (END_MARKER 含む)
        self._recv_buf += data
        if END_MARKER in self._recv_buf and self._recv_event:
            self._recv_event.set()

    async def _scan(self):
        """ArTec Links デバイスをスキャンする。AL- 名またはサービスUUIDで識別。"""
        target_name = self.device_name

        def match(device, adv):
            if target_name:
                return device.name == target_name
            if device.name and device.name.startswith(DEVICE_PREFIX):
                return True
            # 名前が ESP32 等の汎用名の場合はサービスUUIDで識別
            uuids = [str(u).lower() for u in (adv.service_uuids or [])]
            return SERVICE_UUID.lower() in uuids

        device = await BleakScanner.find_device_by_filter(match, timeout=self.timeout)
        if device is None:
            hint = target_name or f'"{DEVICE_PREFIX}*"'
            raise BleConnectionError(
                f"ArTec Links デバイス ({hint}) が見つかりません。"
                "デバイスがボタンを押しながら起動されているか確認してください。"
            )
        return device
