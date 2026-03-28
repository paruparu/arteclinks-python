# arteclinks-python

ArTec Links メインユニット (ESP32-C3 + MicroPython) を Python から制御するライブラリ。
USB と BLE の両方に対応し、LED 制御・ボタンイベント検出・デバイス状態管理を提供する。

## 動作要件

- Python 3.9+
- ArTec Links メインユニット (MicroPython v1.19.1)
- USB 接続の場合: `pyserial`
- BLE 接続の場合: `bleak`

## インストール

### pip

```bash
pip install git+https://github.com/paruparu/arteclinks-python.git
```

### git submodule (推奨)

```bash
git submodule add https://github.com/paruparu/arteclinks-python.git
pip install -e arteclinks-python/
```

---

## クイックスタート

```python
from arteclinks import ArTecLinks

with ArTecLinks.connect_usb() as device:
    device.led.blue()
    device.button.wait_for_press()
    device.led.green()
```

---

## 接続

### USB 接続

```python
device = ArTecLinks.connect_usb()

# ポートを明示する場合
device = ArTecLinks.connect_usb(port="/dev/cu.usbmodem101")  # Mac
device = ArTecLinks.connect_usb(port="COM3")                  # Windows
```

デバイスは **ボタンを押さずに** 起動しておくこと。

### BLE 接続

```python
device = ArTecLinks.connect_ble()

# デバイス名を指定する場合 ("AL-XXXX" 形式)
device = ArTecLinks.connect_ble(device_name="AL-6370")
```

デバイスは **ボタンを押しながら** 起動しておくこと。

### コンテキストマネージャ

`with` 文を使うと切断が自動で行われる。

```python
with ArTecLinks.connect_usb() as device:
    ...
# ブロックを抜けると自動的に disconnect()
```

---

## LED 制御

### RGB 値で指定 (0〜100)

```python
device.led.set(100, 0, 0)    # 赤
device.led.set(0, 50, 100)   # 青寄りの水色
```

範囲外の値は自動的にクランプされる (例: `150 → 100`, `-10 → 0`)。
数値以外を渡すと `TypeError` を送出。

### 色名で指定

```python
device.led.set_color("blue")
device.led.set_color("yellow")
```

使用可能な色名:

| 名前 | 色 |
|------|----|
| `red` | 赤 |
| `green` | 緑 |
| `blue` | 青 |
| `white` | 白 |
| `yellow` | 黄 |
| `cyan` | シアン |
| `magenta` | マゼンタ |
| `orange` | オレンジ |
| `purple` | 紫 |
| `pink` | ピンク |
| `off` | 消灯 |

不明な色名を渡すと `ValueError` を送出。

### ショートカットメソッド

```python
device.led.red()
device.led.green()
device.led.blue()
device.led.white()
device.led.yellow()
device.led.cyan()
device.led.magenta()
device.led.orange()
device.led.purple()
device.led.off()
```

`brightness` 引数で明るさを 0〜100 で調整できる (デフォルト: `100`)。

```python
device.led.blue(brightness=30)   # 薄い青
```

---

## ボタン検出

ボタンは **push 方式** で検出する。デバイス側で IRQ を使って変化を即座に検知し、ホスト側に `PRESS` / `RELEASE` を通知する。ポーリングによるディレイはない。

### 監視の開始・停止

```python
device.button.start_watching()   # 監視開始
device.button.stop_watching()    # 監視停止
```

### コールバック登録

```python
device.button.on_press(lambda: print("押された"))
device.button.on_release(lambda: print("離された"))
```

コールバックは別スレッドで呼ばれるので、ブロッキング処理を書いても問題ない。

### ブロッキング待機

```python
device.button.start_watching()
pressed = device.button.wait_for_press(timeout=10.0)
# True: 押された / False: タイムアウト
```

### 現在値の読み取り (監視なし)

監視していないときにボタンの現在状態を1回だけ読む。

```python
value = device.button.read()         # 0: 押中 / 1: 離中
is_pressed = device.button.is_pressed()  # bool
```

---

## ButtonEvents — 高レベルイベント

`device.events` から直接使えるほか、任意の `Button` インスタンスを渡して生成することもできる。

```python
device.button.start_watching()

device.events.on_click(lambda: print("クリック"))
device.events.on_long_press(lambda: print("長押し"))
device.events.on_double_click(lambda: print("ダブルクリック"))
```

### イベント種別

| イベント | 条件 |
|----------|------|
| `click` | 600ms 未満で離す (短押し) |
| `long_press` | 600ms 以上押し続けて離す |
| `double_click` | 350ms 以内に 2 回クリック |

> **注意**: `on_double_click` を登録すると、`click` イベントは 350ms 遅延して発火する (ダブルクリックでないことを確認するため)。`on_double_click` を登録しなければ `click` は即座に発火する。

### しきい値のカスタマイズ

```python
device.events.LONG_PRESS_MS   = 800   # デフォルト: 600
device.events.DOUBLE_CLICK_MS = 400   # デフォルト: 350
```

### ButtonEvents を単体で使う

```python
from arteclinks import ArTecLinks, ButtonEvents

with ArTecLinks.connect_usb() as device:
    device.button.start_watching()
    ev = ButtonEvents(device.button)
    ev.on_click(my_handler)
```

---

## DeviceState — デバイス状態管理

```python
state = device.state

print(state.led_rgb)        # (0, 0, 100)  ← 現在の LED 色 (r, g, b)
print(state.button_pressed) # False
print(state.connected)      # True
```

`device.state` は毎回最新のスナップショットを返す。`led_rgb` は `led.set()` / `led.off()` を呼ぶたびに自動更新される。

---

## バリデーション

単独でも使用できるユーティリティ関数。

```python
from arteclinks import validate_rgb, validate_color_name, COLORS

r, g, b = validate_rgb(120, 50, -5)
# → (100, 50, 0)  ← クランプ済み

color = validate_color_name("Blue", COLORS)
# → "blue"  ← 小文字に正規化

validate_rgb("red", 0, 0)
# → TypeError: r は数値でなければなりません

validate_color_name("violet", COLORS)
# → ValueError: 不明な色: 'violet'。使用可能: ...
```

---

## suzume-agent 連携例

```python
from arteclinks import ArTecLinks

device = ArTecLinks.connect_usb()
device.led.blue()               # 待機中
device.button.start_watching()

def on_click():
    device.led.yellow()         # 考え中
    response = agent.think()
    device.led.green()          # 応答完了
    agent.speak(response)

def on_long_press():
    device.led.off()
    device.disconnect()

device.events.on_click(on_click)
device.events.on_long_press(on_long_press)
```

---

## ハードウェア仕様

| 項目 | 内容 |
|------|------|
| チップ | ESP32-C3 |
| ファームウェア | MicroPython v1.19.1 (カスタムビルド) |
| USB VID/PID | `0x303a` / `0x1001` (built-in USB JTAG) |
| ボーレート | 115200 |
| LED | NeoPixel WS2812B (Pin 2) |
| ボタン | Pin 3, active low |

## ライセンス

MIT
