"""
BLE ボタン監視テスト。
実行後、デバイスのボタンを数回押したり離したりしてください。
Ctrl-C で終了します。
"""
import time
from arteclinks import ArTecLinks

print('BLE接続中...')
device = ArTecLinks.connect_ble()
print('接続:', device)

device.led.blue()
print('LED青 → 待機中')

device.button.start_watching()
print('ボタン監視開始')

device.button.on_press(lambda: print('  >> PRESS'))
device.button.on_release(lambda: print('  >> RELEASE'))

device.events.on_click(lambda: (print('  >> CLICK'), device.led.green()))
device.events.on_long_press(lambda: (print('  >> LONG PRESS'), device.led.red()))
device.events.on_double_click(lambda: (print('  >> DOUBLE CLICK'), device.led.white()))

print('ボタンを押してみてください (Ctrl-C で終了)')
try:
    while True:
        time.sleep(0.1)
except KeyboardInterrupt:
    pass

device.led.off()
device.disconnect()
print('終了')
