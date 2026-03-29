import asyncio
from bleak import BleakClient, BleakScanner

TX = 'aa560003-d2df-d208-bc74-66d186385587'
RX = 'aa560002-d2df-d208-bc74-66d186385587'
END = b'OK\x04\x04>'

recv_buf = b''
recv_event = asyncio.Event()

def on_notify(sender, data):
    global recv_buf
    recv_buf += data
    if END in recv_buf:
        recv_event.set()

async def exec_cmd(client, code):
    global recv_buf
    recv_buf = b''
    recv_event.clear()
    await client.write_gatt_char(RX, b'\x01' + code.encode() + b'\x04')
    await asyncio.wait_for(recv_event.wait(), timeout=10.0)
    raw = recv_buf[:-len(END)] if recv_buf.endswith(END) else recv_buf
    return raw.decode(errors='replace').strip()

async def main():
    print('スキャン中...')
    dev = await BleakScanner.find_device_by_filter(
        lambda d, _: bool(d.name and ('AL-' in d.name or d.name == 'ESP32')),
        timeout=10.0
    )
    print(f'接続: {dev.name}')

    async with BleakClient(dev.address) as client:
        await client.start_notify(TX, on_notify)

        # ボタンを離した状態
        val = await exec_cmd(client, 'from al.hub import button; print(button.get_value())')
        print(f'ボタン(今): {val}  (0=押中 / 1=離中)')

        print()
        input('>>> ボタンを押したまま Enter を押してください: ')

        val = await exec_cmd(client, 'from al.hub import button; print(button.get_value())')
        print(f'ボタン(押中): {val}  (0=押中 / 1=離中)')

        await client.stop_notify(TX)

asyncio.run(main())
