"""
suzume-agent 連携サンプル。

実際の suzume-agent との接続部分はコメントで示す。
LED でエージェントの状態を表示し、ボタンで人間がトリガーを入力する。
"""
import time
from arteclinks import ArTecLinks

# LED の状態定義
STATE_COLORS = {
    "idle":       "blue",      # 待機中
    "listening":  "cyan",      # 聞いている
    "thinking":   "yellow",    # 考え中
    "speaking":   "green",     # 話している
    "error":      "red",       # エラー
    "sleep":      "off",       # スリープ
}

def run():
    with ArTecLinks.connect_usb() as device:
        print("ArTec Links 接続完了")
        device.led.set_color(STATE_COLORS["idle"])

        while True:
            print("ボタンを押してエージェントを呼んでください...")

            # 人間のボタン入力を待つ
            device.button.wait_for_press()

            try:
                # 聞き取り中
                device.led.set_color(STATE_COLORS["listening"])
                print("[状態] 聞き取り中")
                # audio = record_audio()   # ← 実際の音声録音処理
                time.sleep(1)  # デモ用

                # 処理中
                device.led.set_color(STATE_COLORS["thinking"])
                print("[状態] 考え中")
                # response = agent.process(audio)  # ← エージェント処理
                time.sleep(1)  # デモ用

                # 応答中
                device.led.set_color(STATE_COLORS["speaking"])
                print("[状態] 応答中")
                # speak(response)  # ← 音声合成・再生
                time.sleep(1)  # デモ用

            except Exception as e:
                device.led.set_color(STATE_COLORS["error"])
                print(f"[エラー] {e}")
                time.sleep(2)

            finally:
                # 待機に戻る
                device.led.set_color(STATE_COLORS["idle"])


if __name__ == "__main__":
    run()
