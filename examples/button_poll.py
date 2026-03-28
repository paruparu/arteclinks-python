"""ボタン押下検出サンプル (push方式・ディレイなし)"""
import time
from arteclinks import ArTecLinks

def on_press():
    print("PRESS")
    device.led.green()

def on_release():
    print("RELEASE")
    device.led.blue()

with ArTecLinks.connect_usb() as device:
    device.led.blue()
    device.button.start_watching()
    device.button.on_press(on_press)
    device.button.on_release(on_release)

    print("ボタンを押してください... (Ctrl+C で終了)")
    try:
        while True:
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass

    device.button.stop_watching()
    device.led.off()
    print("終了")
