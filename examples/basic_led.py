"""LED の基本操作サンプル"""
import time
from arteclinks import ArTecLinks

with ArTecLinks.connect_usb() as device:
    print(device)

    for color in ["red", "green", "blue", "yellow", "cyan", "magenta", "white"]:
        print(f"→ {color}")
        device.led.set_color(color)
        time.sleep(0.5)

    device.led.off()
    print("完了")
