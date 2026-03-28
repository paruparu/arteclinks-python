"""
ArTec Links BLE 通信層。

デバイスが BLE モード (起動時にボタンを押す) で動作しているときに使用する。
内部プロトコルは UART-over-BLE:
  - ホスト→デバイス: RX characteristic に b'\\x01' + code + b'\\x04' を write
  - デバイス→ホスト: TX characteristic の notify で受信、b'OK\\x04\\x04>' で終端
"""

import asyncio
from typing import Optional, Callable
from bleak import BleakClient, BleakScanner

# ArTec Links 固有の BLE UUID
SERVICE_UUID   = "AA560001-D2DF-D208-BC74-66D186385587"
TX_CHAR_UUID   = "AA560003-D2DF-D208-BC74-66D186385587"  # デバイス→ホスト (notify)
RX_CHAR_UUID   = "AA560002-D2DF-D208-BC74-66D186385587"  # ホスト→デバイス (write)

DEVICE_PREFIX  = "AL-"   # デバイス名: AL-XXXX (MAC末尾4桁)
END_MARKER     = b'OK\x04\x04>'


class BleReplError(Exception):
    """BLE REPL 実行エラー"""
    pass


class BleConnectionError(Exception):
    """BLE 接続エラー"""
    pass


class BleRepl:
    """
    ArTec Links BLE REPL クライアント。

    デバイス名 "AL-XXXX" を自動スキャンして接続し、
    USB版と同じ exec() インターフェースを提供する。
    """

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
        self._recv_event = asyncio.Event()

    async def open(self) -> None:
        """BLE デバイスをスキャンして接続する"""
        device = await self._scan()
        self._client = BleakClient(device.address)
        await self._client.connect(timeout=self.timeout)
        await self._client.start_notify(TX_CHAR_UUID, self._on_notify)

    async def close(self) -> None:
        """BLE 接続を切断する"""
        if self._client and self._client.is_connected:
            await self._client.stop_notify(TX_CHAR_UUID)
            await self._client.disconnect()
        self._client = None

    async def exec(self, code: str, timeout: Optional[float] = None) -> str:
        """
        Pythonコードをデバイス上で実行し、標準出力を返す。

        Args:
            code: 実行するPythonコード
            timeout: タイムアウト秒数

        Returns:
            標準出力の文字列

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

        # エラーチェック: Traceback が含まれていたらエラーとして扱う
        decoded = raw.decode(errors='replace')
        if 'Traceback' in decoded or 'Error' in decoded:
            raise BleReplError(decoded.strip())

        return decoded

    def _on_notify(self, sender, data: bytes) -> None:
        self._recv_buf += data
        if END_MARKER in self._recv_buf:
            self._recv_event.set()

    async def _scan(self):
        """AL- プレフィックスのデバイスをスキャンする"""
        target_name = self.device_name

        def match(device, adv):
            if target_name:
                return device.name == target_name
            return device.name and device.name.startswith(DEVICE_PREFIX)

        device = await BleakScanner.find_device_by_filter(match, timeout=self.timeout)
        if device is None:
            hint = target_name or f'"{DEVICE_PREFIX}*"'
            raise BleConnectionError(
                f"ArTec Links デバイス ({hint}) が見つかりません。"
                "デバイスがボタンを押しながら起動されているか確認してください。"
            )
        return device

    async def __aenter__(self):
        await self.open()
        return self

    async def __aexit__(self, *args):
        await self.close()
