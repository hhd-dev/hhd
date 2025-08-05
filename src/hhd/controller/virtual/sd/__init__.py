import logging
import time
from collections import defaultdict
from typing import Sequence, cast

from hhd.controller import (
    Consumer,
    Event,
    Producer,
    DEBUG_MODE,
)
from hhd.controller.lib.uhid import UhidDevice, BUS_USB
from hhd.controller.lib.common import encode_axis, set_button
from hhd.controller.lib.ccache import ControllerCache

from .const import (
    SDCONT_VENDOR,
    SDCONT_VERSION,
    SDCONT_COUNTRY,
    SDCONT_DESCRIPTOR,
    SD_AXIS_MAP,
    SD_BTN_MAP,
    SD_SETTINGS,
)

MAX_IMU_SYNC_DELAY = 2

logger = logging.getLogger(__name__)

_cache = ControllerCache()


def trim(rep: bytes):
    if not rep:
        return rep
    idx = len(rep) - 1
    while idx > 0 and rep[idx] == 0x00:
        idx -= 1
    return rep[: idx + 1]


def pad(rep):
    return bytes(rep) + bytes([0 for _ in range(64 - len(rep))])


class SteamdeckController(Producer, Consumer):
    @staticmethod
    def close_cached():
        _cache.close()

    def __init__(
        self,
        pid,
        name,
        touchpad: bool = False,
        sync_gyro: bool = True,
    ) -> None:
        self.available = False
        self.dev = None
        self.start = 0
        self.pid = pid
        self.name = name
        self.sync_gyro = sync_gyro
        self.enable_touchpad = touchpad
        self.report = bytearray(64)
        self.i = 0
        self.last_rep = None

    def open(self) -> Sequence[int]:
        self.available = False
        self.report[0] = 0x01
        self.report[2] = 0x09
        self.report[3] = 0x40
        self.i = 0

        # Use cached controller to avoid disconnects
        cached = cast(
            SteamdeckController | None,
            _cache.get(),
        )
        self.dev = None
        if cached:
            if self.pid == cached.pid and self.name == cached.name:
                logger.warning(
                    f"Using cached controller node for Steamdeck Controller."
                )
                self.dev = cached.dev
                if self.dev and self.dev.fd:
                    self.fd = self.dev.fd
            else:
                logger.warning(f"Throwing away cached Steamdeck Controller.")
                cached.close(True, in_cache=True)
        if not self.dev:
            self.dev = UhidDevice(
                vid=SDCONT_VENDOR,
                pid=self.pid,
                bus=BUS_USB,
                version=SDCONT_VERSION,
                country=SDCONT_COUNTRY,
                name=bytes(self.name, "utf-8"),
                report_descriptor=SDCONT_DESCRIPTOR,
                unique_name=b"",
                physical_name=b"",
            )
            self.fd = self.dev.open()

        self.state: dict = defaultdict(lambda: 0)
        self.rumble = False
        self.touchpad_touch = False
        self.touchpad_left = False
        curr = time.perf_counter()
        self.start = curr
        self.touchpad_down = curr
        self.last_imu = curr
        self.imu_failed = False

        logger.info(f"Starting '{self.name}'.")
        assert self.fd
        return [self.fd]

    def close(self, exit: bool, in_cache: bool = False) -> bool:
        if not in_cache and time.perf_counter() - self.start:
            logger.warning(f"Caching Steam Controller to avoid reconnection.")
            _cache.add(self)
        elif self.dev:
            self.dev.send_destroy()
            self.dev.close()
            self.dev = None
            self.fd = None

        return True

    def produce(self, fds: Sequence[int]) -> Sequence[Event]:
        if not self.fd or not self.dev or self.fd not in fds:
            return []

        # Process queued events
        out: Sequence[Event] = []
        assert self.dev
        while ev := self.dev.read_event():
            match ev["type"]:
                case "open":
                    # logger.info(f"SD OPENED")
                    pass
                case "close":
                    # logger.info(f"SD CLOSED")
                    pass
                case "start":
                    pass
                case "get_report":
                    match self.last_rep:
                        case 0x83:
                            rep = bytes(
                                [
                                    0x83,
                                    0x2D,  # 45/5=9 attrs
                                    # https://github.com/libsdl-org/SDL/blob/eed94cb0345cbf6dc9088c7bfc3d10828cb19f9d/src/joystick/hidapi/steam/controller_constants.h#L363
                                    0x01,  # ATTRIB_PRODUCT_ID
                                    0x05,
                                    0x12,
                                    0x00,
                                    0x00,
                                    0x02,  # ATTRIB_PRODUCT_REVISON
                                    0x00,
                                    0x00,
                                    0x00,
                                    0x00,
                                    0x0A,  # ATTRIB_BOOTLOADER_BUILD_TIME
                                    0x2B,
                                    0x12,
                                    0xA9,
                                    0x62,
                                    0x04,  # ATTRIB_FIRMWARE_BUILD_TIME
                                    0xB7,
                                    0x61,
                                    0x7C,
                                    0x67,
                                    0x09,  # ATTRIB_BOARD_REVISION
                                    0x2E,
                                    0x00,
                                    0x00,
                                    0x00,
                                    0x0B,  # ATTRIB_CONNECTION_INTERVAL_IN_US
                                    0xA0,
                                    0x0F,
                                    0x00,
                                    0x00,
                                    0x0D,  # attr
                                    0x00,
                                    0x00,
                                    0x00,
                                    0x00,
                                    0x0C,  # attr
                                    0x00,
                                    0x00,
                                    0x00,
                                    0x00,
                                    0x0E,  # attr
                                    0x00,
                                    0x00,
                                    0x00,
                                    0x00,
                                ]
                            )
                            if not ev["rnum"]:
                                rep = bytes([0]) + rep
                        case 0xAE:
                            rep = bytes(
                                [
                                    0x00,
                                    0xAE,
                                    0x15,
                                    0x01,
                                    *[0x10 for _ in range(15)],
                                ]
                            )
                        case _:
                            rep = bytes([])
                    self.dev.send_get_report_reply(ev["id"], 0, pad(rep))
                    logger.info(
                        f"GET_REPORT: {ev}\nRESPONSE({self.last_rep:02x}): {rep.hex()}"
                    )
                case "set_report":
                    self.dev.send_set_report_reply(ev["id"], 0)
                    self.last_rep = ev["data"][3]

                    match self.last_rep:
                        case 0xEB:
                            left = int.from_bytes(
                                ev["data"][8:10], byteorder="little", signed=False
                            )
                            right = int.from_bytes(
                                ev["data"][10:12], byteorder="little", signed=False
                            )
                            out.append(
                                {
                                    "type": "rumble",
                                    "code": "main",
                                    # For some reason goes to 127
                                    "strong_magnitude": left / (2**16 - 1),
                                    "weak_magnitude": right / (2**16 - 1),
                                }
                            )
                        case 0xea:
                            # Touchpad stuff
                            pass
                        case 0x8F:
                            # logger.info(f"SD Received Haptics ({time.perf_counter()*1000:.3f}ms):\n{ev['data'].hex().rstrip(' 0')}")
                            pass
                        case 0x87:
                            if DEBUG_MODE:
                                rnum = ev["data"][4]
                                ss = []
                                for i in range(0, rnum, 3):
                                    rtype = ev["data"][5 + i]
                                    rdata = int.from_bytes(
                                        ev["data"][6 + i : 8 + i],
                                        byteorder="little",
                                        signed=False,
                                    )
                                    ss.append(
                                        f"{SD_SETTINGS[rtype] if rtype < len(SD_SETTINGS) else "UKNOWN"} ({rtype:02d}): {rdata:02x}"
                                    )
                                mlen = max(map(len, ss))
                                logger.info(
                                    f"SD Received Settings (n={rnum // 3}):{''.join(map(lambda x: '\n > ' + ' '*(mlen - len(x)) + x, ss))}"
                                )
                        case _:
                            if DEBUG_MODE:
                                logger.info(
                                    f"SD SET_REPORT({ev['rnum']:02x}:{ev['rtype']:02x}): {trim(ev['data']).hex()}"
                                )

                    # 410000eb 0901401f 0000 0000 fbfb
                    # 410000eb 0901401f ff7f ff7f fbfb
                case "output":
                    logger.info(f"SD OUTPUT")
                case _:
                    logger.warning(f"SD UKN_EVENT: {ev}")

        return out

    def consume(self, events: Sequence[Event]):
        if not self.dev:
            return

        assert self.report

        # To fix gyro to mouse in latest steam
        # only send updates when gyro sends a timestamp
        send = not self.sync_gyro
        curr = time.perf_counter()

        new_rep = bytearray(self.report)
        for ev in events:
            code = ev["code"]
            match ev["type"]:
                case "axis":
                    if not self.enable_touchpad and code.startswith("touchpad"):
                        continue
                    if code in SD_AXIS_MAP:
                        try:
                            encode_axis(new_rep, SD_AXIS_MAP[code], ev["value"])
                        except Exception:
                            logger.warning(
                                f"Encoding '{ev['code']}' with {ev['value']} overflowed."
                            )
                    match code:
                        case "gyro_ts" | "accel_ts" | "imu_ts":
                            send = True
                            self.last_imu = time.perf_counter()
                            self.last_imu_ts = ev["value"]
                case "button":
                    if not self.enable_touchpad and code.startswith("touchpad"):
                        continue
                    if code == "touchpad_touch":
                        self.touchpad_touch = ev["value"]
                        if not self.touchpad_left:
                            set_button(
                                new_rep,
                                SD_BTN_MAP["touchpad_touch"],
                                ev["value"] or self.touchpad_touch,
                            )
                    elif code == "touchpad_left":
                        set_button(
                            new_rep,
                            SD_BTN_MAP["touchpad_touch"],
                            ev["value"] or self.touchpad_touch,
                        )
                        set_button(
                            new_rep,
                            SD_BTN_MAP["touchpad_left"],
                            ev["value"],
                        )
                        encode_axis(
                            new_rep,
                            SD_AXIS_MAP["touchpad_force"],
                            ev["value"],
                        )
                        self.touchpad_left = ev["value"]
                    elif code in SD_BTN_MAP:
                        set_button(new_rep, SD_BTN_MAP[code], ev["value"])

        if not self.touchpad_touch:
            encode_axis(
                new_rep,
                SD_AXIS_MAP["touchpad_x"],
                0.5,
            )
            encode_axis(
                new_rep,
                SD_AXIS_MAP["touchpad_y"],
                0.5,
            )

        # If the IMU breaks, smoothly re-enable the controller
        failover = self.last_imu + MAX_IMU_SYNC_DELAY < curr
        if self.sync_gyro and failover and not self.imu_failed:
            self.imu_failed = True
            logger.error(
                f"IMU Did not send information for {MAX_IMU_SYNC_DELAY}s. Disabling Gyro Sync."
            )

        self.report = new_rep
        # sign_crc32_inplace(self.report, DS5_INPUT_CRC32_SEED)
        if send or failover:
            new_rep[4:8] = self.i.to_bytes(4, byteorder="little", signed=False)
            self.i = self.i + 1 if self.i < 0xFFFFFFFF else 0
            self.dev.send_input_report(self.report)
            # logger.info(self.report.hex())
