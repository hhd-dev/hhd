import logging
import time
from collections import defaultdict
from typing import Sequence, cast, Literal

from hhd.controller import (
    Consumer,
    Event,
    Producer,
)
from hhd.controller.lib.common import encode_axis, set_button
from hhd.controller.lib.uhid import BUS_BLUETOOTH, BUS_USB, UhidDevice
from hhd.controller.lib.ccache import ControllerCache

from .const import (
    SINPUT_HID_REPORT,
    SINPUT_BTN_MAP,
    SINPUT_AXIS_MAP,
    get_button_mask,
    GYRO_MAX_DPS,
    ACCEL_MAX_G,
    SINPUT_AVAILABLE_BUTTONS,
    SDL_SUBTYPE_XINPUT_SHARE_NONE,
    SDL_SUBTYPE_XINPUT_SHARE_DUAL,
    SDL_SUBTYPE_XINPUT_SHARE_QUAD,
    SDL_SUBTYPE_XINPUT_SHARE_NONE_CLICK,
    SDL_SUBTYPE_XINPUT_SHARE_DUAL_CLICK,
    SDL_SUBTYPE_XINPUT_SHARE_QUAD_CLICK,
)

SINPUT_NANE = "S-Input (HHD)"
MAX_IMU_SYNC_DELAY = 2

logger = logging.getLogger(__name__)

_cache = ControllerCache()


def prefill_report():
    """Prefill the report with zeros."""
    report = bytearray(64)
    report[0] = 0x01  # Report type
    encode_axis(report, SINPUT_AXIS_MAP["lt"], 0)
    encode_axis(report, SINPUT_AXIS_MAP["rt"], 0)
    return report


class SInputController(Producer, Consumer):
    @staticmethod
    def close_cached():
        _cache.close()

    def __init__(
        self,
        enable_touchpad: bool = True,
        touchpad_click: bool = False,
        enable_rgb: bool = True,
        enable_gyro: bool = True,
        sync_gyro: bool = False,
        controller_id: int = 0,
        glyphs: Literal["standard", "xbox", "sony", "nintendo"] = "standard",
        paddles: Literal["none", "dual", "quad"] = "none",
        cache: bool = False,
    ) -> None:
        self.enable_touchpad = enable_touchpad
        self.enable_rgb = enable_rgb
        self.enable_gyro = enable_gyro
        self.sync_gyro = sync_gyro
        self.controller_id = controller_id
        self.glyphs = glyphs
        self.paddles = paddles
        self.touchpad_click = touchpad_click
        self.btns = {}

        self.settings = (
            enable_touchpad,
            enable_rgb,
            enable_gyro,
            sync_gyro,
            controller_id,
            glyphs,
            paddles,
        )

        self.cache = cache
        self.report = prefill_report()
        self.dev: UhidDevice | None = None
        self.fd: int | None = None
        self.available = False

    def open(self) -> Sequence[int]:
        self.available = False
        self.report = prefill_report()

        cached = cast(SInputController | None, _cache.get())

        # Use cached controller to avoid disconnects
        self.dev = None
        if cached:
            if self.settings == cached.settings:
                logger.warning(f"Using cached controller node for SInput.")
                self.dev = cached.dev
                if self.dev and self.dev.fd:
                    self.fd = self.dev.fd
            else:
                logger.warning(f"Throwing away cached Sinput controller.")
                cached.close(True, in_cache=True)
        if not self.dev:
            self.dev = UhidDevice(
                vid=0x2E8A,
                pid=0x10C6,
                bus=BUS_USB,
                version=256,
                country=0,
                name=SINPUT_NANE.encode(),
                report_descriptor=(SINPUT_HID_REPORT),
            )
            self.fd = self.dev.open()

        self.state: dict = defaultdict(lambda: 0)
        self.rumble = False
        self.touchpad_touch = False
        curr = time.perf_counter()
        self.touchpad_down = curr
        self.last_imu = curr
        self.imu_failed = False
        self.start = time.perf_counter()

        logger.info(
            f"Starting S-Input controller with RGB={self.enable_rgb}, touchpad={self.enable_touchpad}."
        )
        assert self.fd
        return [self.fd]

    def close(self, exit: bool, in_cache: bool = False) -> bool:
        if not in_cache and self.cache and time.perf_counter() - self.start:
            logger.warning(f"Caching SInput device to avoid reconnection.")
            _cache.add(self)
        elif self.dev:
            self.dev.send_destroy()
            self.dev.close()
            self.dev = None
            self.fd = None

        return True

    def produce(self, fds: Sequence[int]) -> Sequence[Event]:
        if self.fd not in fds:
            return []

        # Process queued events
        out: Sequence[Event] = []
        assert self.dev
        while ev := self.dev.read_event():
            match ev["type"]:
                case "open":
                    self.available = True
                case "close":
                    self.available = False
                case "output":
                    rep = ev["data"]
                    logger.info(rep.hex())
                    if rep[0] != 0x03:
                        logger.warning(
                            f"Received unexpected report type {rep[0]:02x}: {rep.hex()}"
                        )
                        continue

                    match rep[1]:
                        case 0x02:
                            # Feature report
                            feats = bytearray(64)
                            feats[0] = 0x02
                            feats[1] = 0x02

                            #
                            # Features
                            #

                            ofs = 2

                            # Protocol version
                            feats[ofs : ofs + 2] = (0x01, 0x00)

                            # Enable all features except player led
                            feats[ofs + 2] = (
                                0x01
                                + self.enable_gyro * (0x04 + 0x08)
                                + 0x10
                                + 0x20
                                + 0x40
                                + 0x80
                            )
                            # We are a handheld, with touchpad, and rgb
                            feats[ofs + 3] = (
                                self.enable_touchpad * 0x01
                                + self.enable_rgb * 0x02
                                + 0x04
                            )

                            # Set SDL types based on available buttons
                            gtype = 0x02
                            if self.touchpad_click:
                                match self.paddles:
                                    case "none":
                                        gtype = SDL_SUBTYPE_XINPUT_SHARE_NONE_CLICK
                                    case "dual":
                                        gtype = SDL_SUBTYPE_XINPUT_SHARE_DUAL_CLICK
                                    case "quad":
                                        gtype = SDL_SUBTYPE_XINPUT_SHARE_QUAD_CLICK
                            else:
                                match self.paddles:
                                    case "none":
                                        gtype = SDL_SUBTYPE_XINPUT_SHARE_NONE
                                    case "dual":
                                        gtype = SDL_SUBTYPE_XINPUT_SHARE_DUAL
                                    case "quad":
                                        gtype = SDL_SUBTYPE_XINPUT_SHARE_QUAD

                            match self.glyphs:
                                case "standard":
                                    feats[ofs + 4] = 0x01
                                    feats[ofs + 5] = (1 << 5) | gtype
                                case "xbox":
                                    feats[ofs + 4] = 0x03
                                    feats[ofs + 5] = (1 << 5) | gtype
                                case "sony":
                                    feats[ofs + 4] = 0x06
                                    feats[ofs + 5] = (4 << 5) | gtype
                                case "nintendo":
                                    feats[ofs + 4] = 0x07
                                    feats[ofs + 5] = (3 << 5) | gtype

                            feats[ofs + 6] = 5
                            # Accelerometer scale
                            feats[ofs + 8 : ofs + 10] = int.to_bytes(
                                ACCEL_MAX_G, 2, "little"
                            )
                            feats[ofs + 10 : ofs + 12] = int.to_bytes(
                                GYRO_MAX_DPS, 2, "little"
                            )

                            bmask = get_button_mask(ofs + 12)
                            self.btns = SINPUT_AVAILABLE_BUTTONS[gtype]
                            for key in self.btns:
                                set_button(feats, bmask[key], True)

                            #
                            # Serial
                            #
                            feats[ofs + 18] = 0x53
                            feats[ofs + 19] = 0x35
                            feats[ofs + 23] = self.controller_id

                            logger.info(feats.hex())
                            self.dev.send_input_report(feats)
                        case 1:
                            if rep[2] != 0x02:
                                continue
                            out.append(
                                {
                                    "type": "rumble",
                                    "code": "main",
                                    "strong_magnitude": rep[3] / 255,
                                    "weak_magnitude": rep[5] / 255,
                                }
                            )
                        case 4:
                            red, green, blue = rep[2:5]

                            # Crunch lower values since steam is bugged
                            if red < 3 and green < 3 and blue < 3:
                                red = 0
                                green = 0
                                blue = 0

                            logger.info(f"Changing leds to RGB: {red} {green} {blue}")

                            out.append(
                                {
                                    "type": "led",
                                    "code": "main",
                                    "mode": "solid",
                                    # "brightness": led_brightness / 63
                                    # if led_brightness
                                    # else 1,
                                    "initialize": False,
                                    "direction": "left",
                                    "speed": 0,
                                    "brightness": 1,
                                    "speedd": "high",
                                    "brightnessd": "high",
                                    "red": red,
                                    "blue": blue,
                                    "green": green,
                                    "red2": 0,  # disable for OXP
                                    "blue2": 0,
                                    "green2": 0,
                                    "oxp": None,
                                }
                            )
                        case _:
                            logger.info(rep.hex())
                case _:
                    logger.debug(f"Received unhandled report:\n{ev}")
        return out

    def consume(self, events: Sequence[Event]):
        assert self.dev and self.report
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
                    if code in SINPUT_AXIS_MAP:
                        try:
                            encode_axis(new_rep, SINPUT_AXIS_MAP[code], ev["value"])
                        except Exception:
                            logger.warning(
                                f"Encoding '{ev['code']}' with {ev['value']} overflowed."
                            )
                    # DPAD is weird
                    match code:
                        case "gyro_ts" | "accel_ts" | "imu_ts":
                            send = True
                            self.last_imu = time.perf_counter()
                            self.last_imu_ts = ev["value"]
                            new_rep[19:23] = int(ev["value"] / 1000).to_bytes(
                                8, byteorder="little", signed=False
                            )[:4]
                case "button":
                    if not self.enable_touchpad and code.startswith("touchpad"):
                        continue

                    if code in self.btns and code in SINPUT_BTN_MAP:
                        set_button(new_rep, SINPUT_BTN_MAP[code], ev["value"])

                    # Fix touchpad click requiring touch
                    if code == "touchpad_touch":
                        self.touchpad_touch = ev["value"]
                    if code == "touchpad_left":
                        set_button(
                            new_rep,
                            SINPUT_BTN_MAP["touchpad_pressure"],
                            ev["value"] or self.touchpad_touch,
                        )

        # Cache
        # Caching can cause issues since receivers expect reports
        # at least a couple of times per second
        # if new_rep == self.report and not self.fake_timestamps:
        #     return
        self.report = new_rep

        # If the IMU breaks, smoothly re-enable the controller
        failover = self.last_imu + MAX_IMU_SYNC_DELAY < curr
        if self.sync_gyro and failover and not self.imu_failed:
            self.imu_failed = True
            logger.error(
                f"IMU Did not send information for {MAX_IMU_SYNC_DELAY}s. Disabling Gyro Sync."
            )

        if failover:
            new_rep[19:23] = int(time.perf_counter_ns() // 1000).to_bytes(
                8, byteorder="little", signed=False
            )[:4]

        if send or failover:
            # logger.info(self.report.hex())
            self.dev.send_input_report(self.report)
