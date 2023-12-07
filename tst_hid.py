import logging
import select
from time import sleep

logging.basicConfig(level=logging.INFO)

from hhd.controller.lib.hid import enumerate_unique
from hhd.controller.physical.hidraw import GenericGamepadHidraw, AM, BM, decode_axis
from hhd.device.legion_go import LGO_RAW_INTERFACE_BTN_MAP, LGO_RAW_INTERFACE_AXIS_MAP

v = GenericGamepadHidraw(
    vid=[0x17EF],
    pid=[
        0x6182,  # XINPUT
        0x6183,  # DINPUT
        0x6184,  # Dual DINPUT
        0x6185,  # FPS
    ],
    usage_page=[0xFFA0],
    usage=[0x0001],
    report_size=64,
    axis_map=LGO_RAW_INTERFACE_AXIS_MAP,
    btn_map=LGO_RAW_INTERFACE_BTN_MAP,
)
v.open()
assert v.dev

try:
    ld = None
    while True:
        select.select([v.fd], [], [])
        ev = v.produce([v.fd])
        d = v.report
        if d and d != ld:
            out = f"[Ukn:"
            out += f" {d[:14].hex()}"
            out += f"][Sticks:"
            out += f" {d[14]:02x}"
            out += f" {d[15]:02x}"
            out += f" {d[16]:02x}"
            out += f" {d[17]:02x}"
            out += f"][Buttons"
            out += f" {d[18]:08b}"
            out += f" {d[19]:08b}"
            out += f" {d[20]:08b}"
            out += f"][Btn_mid:"
            out += f" {d[21]:02x}"
            out += f"][Trig:"
            out += f" {d[22]:02x}"
            out += f" {d[23]:02x}"
            out += f"][Ukn:"
            out += f" {d[24]:02x}"
            out += f"][Scroll:"
            out += f" {d[25]:02x}"
            out += f"][Touchpad:"
            out += f" {d[26:28].hex()}"
            out += f" {d[28:30].hex()}"
            out += f" [Gyro LR:"
            out += f" {d[30:34].hex(' ', 1)}"
            out += f"][Ukn:"
            out += f" {d[34:].hex()}"
            out += f"]"
            print(out)
            if ev:
                print(ev)
        # sleep a lil so stuff doesnt collapse
        ld = d
        sleep(0.01)
except KeyboardInterrupt:
    pass
