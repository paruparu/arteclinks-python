"""
MicroPython raw REPL 通信層。

ArTec Links メインユニット (ESP32-C3) との USB シリアル通信を担う。
raw REPL モードでPythonコードを送信し、結果を受信する。
"""

import serial
import threading
import time
from typing import Callable, Optional


class ReplError(Exception):
    """デバイス上でのPython実行エラー"""
    pass


class ConnectionError(Exception):
    """シリアル接続エラー"""
    pass


class RawRepl:
    """
    MicroPython raw REPL プロトコル実装。

    raw REPL モード:
      Ctrl-A (0x01) で入る
      コード + Ctrl-D (0x04) で実行
      "OK" + stdout + 0x04 + stderr + 0x04 + ">" が返る

    BleRepl と共通のインターフェースを持つ:
        exec_stream / stop_stream / pause_stream / resume_stream / write_stream
        supports_stream_write / monitor_script
    """

    supports_stream_write: bool = True

    CTRL_C = b'\x03'
    CTRL_A = b'\x01'
    CTRL_D = b'\x04'
    CTRL_B = b'\x02'

    def __init__(self, port: str, baudrate: int = 115200, timeout: float = 5.0):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self._serial: Optional[serial.Serial] = None

        # ストリームモード
        self._stream_mode = False
        self._stream_handler: Optional[Callable[[str], None]] = None
        self._stream_thread: Optional[threading.Thread] = None
        self._paused_handler: Optional[Callable[[str], None]] = None

        # シリアルポートへのアクセスをシリアライズするロック
        self._lock = threading.Lock()

    def open(self) -> None:
        """シリアルポートを開き、raw REPL モードに入る"""
        try:
            self._serial = serial.Serial(
                self.port,
                self.baudrate,
                timeout=self.timeout,
                exclusive=True,
            )
        except serial.SerialException as e:
            raise ConnectionError(f"ポートを開けません ({self.port}): {e}") from e

        time.sleep(0.1)
        for _ in range(4):
            self._serial.write(self.CTRL_C)
            time.sleep(0.08)
        time.sleep(0.2)
        self._serial.read_all()

        self._serial.write(self.CTRL_A)
        time.sleep(0.3)
        self._serial.read_all()

    def close(self) -> None:
        """通常 REPL に戻してポートを閉じる"""
        self.stop_stream()
        if self._serial and self._serial.is_open:
            try:
                self._serial.write(self.CTRL_B)
                time.sleep(0.1)
            except Exception:
                pass
            self._serial.close()
        self._serial = None

    def exec(self, code: str, timeout: Optional[float] = None) -> str:
        """
        Pythonコードをデバイス上で実行し、標準出力を返す。

        Raises:
            ReplError: デバイス上で例外が発生した場合
            ConnectionError: 接続が切れている場合
        """
        if not self._serial or not self._serial.is_open:
            raise ConnectionError("デバイスに接続されていません")

        t = timeout or self.timeout
        self._serial.timeout = t

        payload = code.encode() + self.CTRL_D
        self._serial.write(payload)

        ok = self._serial.read(2)
        if ok != b'OK':
            self._serial.write(self.CTRL_C)
            time.sleep(0.1)
            self._serial.read_all()
            self._serial.write(self.CTRL_A)
            time.sleep(0.1)
            self._serial.read_all()
            self._serial.write(payload)
            ok = self._serial.read(2)
            if ok != b'OK':
                raise ConnectionError("raw REPL の同期に失敗しました")

        stdout = self._read_until(b'\x04')
        stderr = self._read_until(b'\x04')
        self._serial.read(1)  # ">"

        if stderr:
            raise ReplError(stderr.decode(errors='replace').strip())

        return stdout.decode(errors='replace')

    # ----------------------------------------------------------------
    # ストリームモード
    # ----------------------------------------------------------------

    def exec_stream(self, code: str, on_line: Callable[[str], None]) -> None:
        """
        長時間実行スクリプトをデバイスに送り込み、出力行をコールバックで受ける。

        デバイスから改行区切りで届く文字列を on_line に渡す。
        停止するには stop_stream() を呼ぶ。

        Args:
            code:    実行する Python コード
            on_line: 出力行ごとに呼ばれるコールバック
        """
        if not self._serial or not self._serial.is_open:
            raise ConnectionError("デバイスに接続されていません")

        payload = code.encode() + self.CTRL_D
        self._serial.write(payload)

        self._serial.timeout = 0.5
        ok = self._serial.read(2)
        if ok != b'OK':
            raise ConnectionError("raw REPL の同期に失敗しました (exec_stream)")

        self._stream_mode = True
        self._stream_handler = on_line

        self._stream_thread = threading.Thread(
            target=self._stream_reader, daemon=True
        )
        self._stream_thread.start()

    def stop_stream(self) -> None:
        """ストリームモードを停止し、raw REPL モードに戻す"""
        if not self._stream_mode:
            return
        self._exit_stream()

    def pause_stream(self) -> None:
        """一時的にストリームを止める (exec() を挟むため)。ロック取得済みで呼ぶこと"""
        if not self._stream_mode:
            return
        self._paused_handler = self._stream_handler
        self._exit_stream()

    def resume_stream(self, script: str) -> None:
        """pause_stream() で止めたストリームを再開する。ロック取得済みで呼ぶこと"""
        if self._stream_mode or not self._paused_handler:
            return
        self.exec_stream(script, self._paused_handler)
        self._paused_handler = None

    def write_stream(self, data: bytes) -> None:
        """
        ストリームモード中にデバイスの stdin へデータを書き込む。
        ストリームを止めずに LED コマンドなどを送る際に使用。
        ロック取得済みで呼ぶこと。
        """
        if not self._serial or not self._serial.is_open:
            raise ConnectionError("デバイスに接続されていません")
        self._serial.write(data)

    def _exit_stream(self) -> None:
        self._stream_mode = False
        self._stream_handler = None

        # まずリーダースレッドを止めてからシリアルを触る
        # (read タイムアウト 0.5s 以内にスレッドが終わる)
        if self._stream_thread:
            self._stream_thread.join(timeout=1.0)
            self._stream_thread = None

        if self._serial and self._serial.is_open:
            self._serial.write(self.CTRL_C)
            self._serial.write(self.CTRL_C)
            time.sleep(0.2)
            self._serial.read_all()
            self._serial.write(self.CTRL_A)
            time.sleep(0.1)
            self._serial.read_all()

    def _stream_reader(self) -> None:
        """バックグラウンドスレッド: 行を読んでコールバックに渡す"""
        buf = ''
        while self._stream_mode:
            try:
                chunk = self._serial.read(64)
                if chunk:
                    buf += chunk.decode(errors='replace')
                    while '\n' in buf:
                        line, buf = buf.split('\n', 1)
                        line = line.strip()
                        if line and self._stream_handler:
                            self._stream_handler(line)
            except Exception:
                break

    # ----------------------------------------------------------------
    # 内部
    # ----------------------------------------------------------------

    def _read_until(self, terminator: bytes) -> bytes:
        buf = b''
        while True:
            c = self._serial.read(1)
            if not c:
                break
            if c == terminator:
                break
            buf += c
        return buf

    @property
    def monitor_script(self) -> str:
        """USB用ボタン監視スクリプト"""
        from .button import _MONITOR_SCRIPT
        return _MONITOR_SCRIPT

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *args):
        self.close()
