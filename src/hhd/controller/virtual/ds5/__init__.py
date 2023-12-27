import logging
import time
from collections import defaultdict
from typing import Literal, NamedTuple, Sequence, cast

from hhd.controller import Consumer, Event, Producer
from hhd.controller.lib.common import encode_axis, set_button
from hhd.controller.lib.uhid import UhidDevice, BUS_USB, BUS_BLUETOOTH

from .const import (
    DS5_USB_AXIS_MAP,
    DS5_USB_BTN_MAP,
    DS5_BT_AXIS_MAP,
    DS5_BT_BTN_MAP,
    DS5_INPUT_REPORT_BT_OFS,
    DS5_INPUT_REPORT_USB_OFS,
    DS5_EDGE_COUNTRY,
    DS5_EDGE_DELTA_TIME_NS,
    DS5_EDGE_DESCRIPTOR_BT,
    DS5_EDGE_DESCRIPTOR_USB,
    DS5_EDGE_MAX_REPORT_FREQ,
    DS5_EDGE_MIN_REPORT_FREQ,
    DS5_EDGE_NAME,
    DS5_EDGE_PRODUCT,
    prefill_ds5_report,
    DS5_EDGE_STOCK_REPORTS,
    DS5_EDGE_TOUCH_HEIGHT,
    sign_crc32_append,
    DS5_FEATURE_CRC32_SEED,
    DS5_INPUT_CRC32_SEED,
    sign_crc32_inplace,
    DS5_EDGE_TOUCH_WIDTH,
    DS5_EDGE_VENDOR,
    DS5_EDGE_VERSION,
    patch_dpad_val,
)

REPORT_MAX_DELAY = 1 / DS5_EDGE_MIN_REPORT_FREQ
REPORT_MIN_DELAY = 1 / DS5_EDGE_MAX_REPORT_FREQ
DS5_EDGE_MIN_TIMESTAMP_INTERVAL = 1500

logger = logging.getLogger(__name__)


class TouchpadCorrection(NamedTuple):
    x_mult: float = 1
    x_ofs: float = 0
    x_clamp: tuple[float, float] = (0, 1)
    y_mult: float = 1
    y_ofs: float = 0
    y_clamp: tuple[float, float] = (0, 1)


TouchpadCorrectionType = Literal[
    "stretch",
    "crop_center",
    "crop_start",
    "crop_end",
    "contain_start",
    "contain_end",
    "contain_center",
    "disabled",
]


def correct_touchpad(
    width: int, height: int, aspect: float, method: TouchpadCorrectionType
):
    dst = width / height
    src = aspect
    ratio = dst / src

    match method:
        case "crop_center":
            if ratio > 1:
                new_width = width / ratio
                return TouchpadCorrection(
                    x_mult=new_width,
                    x_ofs=(width - new_width) / 2,
                    y_mult=height,
                    y_ofs=0,
                )
            else:
                new_height = height * ratio
                return TouchpadCorrection(
                    x_mult=width,
                    x_ofs=0,
                    y_mult=new_height,
                    y_ofs=(height - new_height) / 2,
                )
        case "crop_start":
            if ratio > 1:
                new_width = width / ratio
                return TouchpadCorrection(
                    x_mult=new_width,
                    x_ofs=0,
                    y_mult=height,
                    y_ofs=0,
                )
            else:
                new_height = height * ratio
                return TouchpadCorrection(
                    x_mult=width,
                    x_ofs=0,
                    y_mult=new_height,
                    y_ofs=0,
                )
        case "crop_end":
            if ratio > 1:
                new_width = width / ratio
                return TouchpadCorrection(
                    x_mult=new_width,
                    x_ofs=(width - new_width),
                    y_mult=height,
                    y_ofs=0,
                )
            else:
                new_height = height * ratio
                return TouchpadCorrection(
                    x_mult=width,
                    x_ofs=0,
                    y_mult=new_height,
                    y_ofs=(height - new_height),
                )
        case "contain_center":
            if ratio > 1:
                bound = (ratio - 1) / ratio / 2
                return TouchpadCorrection(
                    x_mult=width, y_mult=height, y_clamp=(bound, 1 - bound)
                )
            else:
                bound = (1 - ratio) / 2
                return TouchpadCorrection(
                    x_mult=width, y_mult=height, x_clamp=(bound, 1 - bound)
                )
        case "contain_start":
            if ratio > 1:
                bound = (ratio - 1) / ratio
                return TouchpadCorrection(
                    x_mult=width, y_mult=height, y_clamp=(0, 1 - bound)
                )
            else:
                bound = (1 - ratio) / 2
                return TouchpadCorrection(
                    x_mult=width, y_mult=height, x_clamp=(0, 1 - bound)
                )
        case "contain_end":
            if ratio > 1:
                bound = (ratio - 1) / ratio
                return TouchpadCorrection(
                    x_mult=width, y_mult=height, y_clamp=(bound, 1)
                )
            else:
                bound = (1 - ratio) / 2
                return TouchpadCorrection(
                    x_mult=width, y_mult=height, x_clamp=(bound, 1)
                )
        case "stretch" | "disabled":
            return TouchpadCorrection(x_mult=width, y_mult=height)

    logger.error(f"Touchpad correction method '{method}' not found.")
    return TouchpadCorrection(x_mult=width, y_mult=height)


class DualSense5Edge(Producer, Consumer):
    def __init__(
        self,
        touchpad_method: TouchpadCorrectionType = "crop_end",
        use_bluetooth: bool = True,
        fake_timestamps: bool = False,
    ) -> None:
        self.available = False
        self.report = None
        self.dev = None
        self.start = 0
        self.use_bluetooth = use_bluetooth
        self.fake_timestamps = fake_timestamps
        self.touchpad_method: TouchpadCorrectionType = touchpad_method

        self.ofs = (
            DS5_INPUT_REPORT_BT_OFS if use_bluetooth else DS5_INPUT_REPORT_USB_OFS
        )
        self.axis_map = DS5_BT_AXIS_MAP if use_bluetooth else DS5_USB_AXIS_MAP
        self.btn_map = DS5_BT_BTN_MAP if use_bluetooth else DS5_USB_BTN_MAP

    def open(self) -> Sequence[int]:
        self.available = False
        self.report = bytearray(prefill_ds5_report(self.use_bluetooth))
        self.dev = UhidDevice(
            vid=DS5_EDGE_VENDOR,
            pid=DS5_EDGE_PRODUCT,
            bus=BUS_BLUETOOTH if self.use_bluetooth else BUS_USB,
            version=DS5_EDGE_VERSION,
            country=DS5_EDGE_COUNTRY,
            name=DS5_EDGE_NAME,
            report_descriptor=DS5_EDGE_DESCRIPTOR_BT
            if self.use_bluetooth
            else DS5_EDGE_DESCRIPTOR_USB,
        )

        self.touch_correction = correct_touchpad(
            DS5_EDGE_TOUCH_WIDTH, DS5_EDGE_TOUCH_HEIGHT, 1, self.touchpad_method
        )

        self.state: dict = defaultdict(lambda: 0)
        self.rumble = False
        self.touchpad_touch = False
        self.start = time.perf_counter_ns()
        self.fd = self.dev.open()

        logger.info(f"Starting '{DS5_EDGE_NAME.decode()}'.")
        return [self.fd]

    def close(self, exit: bool) -> bool:
        if not exit:
            """This is a consumer, so we would deadlock if it was disabled."""
            return False

        if self.dev:
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
                case "get_report":
                    if ev["rnum"] in DS5_EDGE_STOCK_REPORTS:
                        rep = DS5_EDGE_STOCK_REPORTS[ev["rnum"]]
                        if self.use_bluetooth:
                            rep = sign_crc32_append(rep, DS5_FEATURE_CRC32_SEED)
                        self.dev.send_get_report_reply(ev["id"], 0, rep)
                    else:
                        logger.warning(
                            f"DS5: Received get_report with the id (uknown): {ev['rnum']}"
                        )
                case "set_report":
                    logger.warning(
                        f"DS5: Received set_report with the id (uknown): {ev['rnum']}"
                    )
                case "output":
                    invalid = False
                    # Check report num
                    if ev["report"] != 0x01:
                        invalid = True

                    # Check report ids depending on modes
                    if not self.use_bluetooth and ev["data"][0] != 0x02:
                        invalid = True
                    if self.use_bluetooth and ev["data"][0] != 0x31:
                        invalid = True

                    if invalid:
                        logger.warning(
                            f"DS5: Received uknown output report with the following data:\n{ev['report']}: {ev['data'].hex()}"
                        )
                        continue

                    rep = ev["data"]

                    if self.use_bluetooth:
                        # skip seq_tag, tag sent by bluetooth report
                        # rest is the same

                        # If the first byte is the sequence byte, it will be
                        # from 0x00 to 0xF0. Otherwise, for sdl that does not
                        # have it it will be 0x02.
                        # Only the kernel appends the sequence byte
                        # SDL does not
                        if rep[1] == 0x02:
                            rep = rep[0:1] + rep[2:]
                        else:
                            rep = rep[0:1] + rep[3:]

                    if rep[2] & 4:  # DS_OUTPUT_VALID_FLAG1_LIGHTBAR_CONTROL_ENABLE
                        # Led data is being set
                        led_brightness = rep[43]
                        player_leds = rep[44]
                        red = rep[45]
                        green = rep[46]
                        blue = rep[47]
                        if red == 0 and green == 0 and blue == 128:
                            # Skip playstation driver initialization
                            continue
                        if red == 0 and green == 0 and blue == 64:
                            # Skip SDL led initialization
                            continue
                        if red == 64 and green == 0 and blue == 0:
                            # Skip rare SDL led initialization that is offset
                            continue
                        logger.info(f"Changing leds to RGB: {red} {green} {blue}")
                        out.append(
                            {
                                "type": "led",
                                "code": "main",
                                "mode": "solid",
                                "brightness": led_brightness / 63
                                if led_brightness
                                else 1,
                                "speed": 0,
                                "red": red,
                                "blue": blue,
                                "green": green,
                            }
                        )
                    elif (rep[39] & 2) and (rep[42] & 2):
                        # flag2 is DS_OUTPUT_VALID_FLAG2_LIGHTBAR_SETUP_CONTROL_ENABLE
                        # lightbar_setup is DS_OUTPUT_LIGHTBAR_SETUP_LIGHT_OUT
                        # FIXME: Disable for now to avoid hid_playstation messing
                        # with the leds
                        # out.append(
                        #     {
                        #         "type": "led",
                        #         "code": "main",
                        #         "mode": "disable",
                        #         "brightness": 0,
                        #         "speed": 0,
                        #         "red": 0,
                        #         "blue": 0,
                        #         "green": 0,
                        #     }
                        # )
                        pass

                    if rep[1] & 0x02:
                        right = rep[3]
                        left = rep[4]
                        out.append(
                            {
                                "type": "rumble",
                                "code": "main",
                                "strong_magnitude": left / 63,
                                "weak_magnitude": right / 63,
                            }
                        )
                        self.rumble = True
                    elif self.rumble:
                        self.rumble = False
                        out.append(
                            {
                                "type": "rumble",
                                "code": "main",
                                "strong_magnitude": 0,
                                "weak_magnitude": 0,
                            }
                        )
                case _:
                    logger.debug(f"Received unhandled report:\n{ev}")
        return out

    def consume(self, events: Sequence[Event]):
        assert self.dev and self.report

        new_rep = bytearray(self.report)
        for ev in events:
            match ev["type"]:
                case "axis":
                    if ev["code"] in self.axis_map:
                        encode_axis(new_rep, self.axis_map[ev["code"]], ev["value"])
                    # DPAD is weird
                    match ev["code"]:
                        case "hat_x":
                            self.state["hat_x"] = ev["value"]
                            patch_dpad_val(
                                new_rep,
                                self.ofs,
                                self.state["hat_x"],
                                self.state["hat_y"],
                            )
                        case "hat_y":
                            self.state["hat_y"] = ev["value"]
                            patch_dpad_val(
                                new_rep,
                                self.ofs,
                                self.state["hat_x"],
                                self.state["hat_y"],
                            )
                        case "touchpad_x":
                            tc = self.touch_correction
                            x = int(
                                min(max(ev["value"], tc.x_clamp[0]), tc.x_clamp[1])
                                * tc.x_mult
                                + tc.x_ofs
                            )
                            new_rep[self.ofs + 33] = x & 0xFF
                            new_rep[self.ofs + 34] = (new_rep[self.ofs + 34] & 0xF0) | (
                                x >> 8
                            )
                        case "touchpad_y":
                            tc = self.touch_correction
                            y = int(
                                min(max(ev["value"], tc.y_clamp[0]), tc.y_clamp[1])
                                * tc.y_mult
                                + tc.y_ofs
                            )
                            new_rep[self.ofs + 34] = (new_rep[self.ofs + 34] & 0x0F) | (
                                (y & 0x0F) << 4
                            )
                            new_rep[self.ofs + 35] = y >> 4
                        case "gyro_ts":
                            new_rep[self.ofs + 27 : self.ofs + 31] = int(
                                ev["value"] / DS5_EDGE_DELTA_TIME_NS
                            ).to_bytes(8, byteorder="little", signed=False)[:4]
                case "button":
                    if ev["code"] in self.btn_map:
                        set_button(new_rep, self.btn_map[ev["code"]], ev["value"])

                    # Fix touchpad click requiring touch, and also activate second
                    # button for right click
                    if ev["code"] == "touchpad_touch":
                        self.touchpad_touch = ev["value"]
                    if ev["code"] == "touchpad_click":
                        set_button(
                            new_rep,
                            self.btn_map["touchpad_touch"],
                            ev["value"] or self.touchpad_touch,
                        )
                        set_button(
                            new_rep,
                            self.btn_map["touchpad_touch2"],
                            ev["value"],
                        )

                case "configuration":
                    match ev["code"]:
                        case "touchpad_aspect_ratio":
                            self.aspect_ratio = cast(float, ev["value"])
                            self.touch_correction = correct_touchpad(
                                DS5_EDGE_TOUCH_WIDTH,
                                DS5_EDGE_TOUCH_HEIGHT,
                                self.aspect_ratio,
                                self.touchpad_method,
                            )
                        case "is_attached":
                            new_rep[self.ofs + 52] = (new_rep[self.ofs + 52] & 0x0F) | (
                                0x10 if ev["value"] else 0x00
                            )
                        case "battery":
                            new_rep[self.ofs + 52] = (new_rep[self.ofs + 52] & 0xF0) | (
                                max(ev["value"] // 10, 0)
                            )

        # Cache
        if new_rep == self.report and not self.fake_timestamps:
            return
        self.report = new_rep

        if self.fake_timestamps:
            new_rep[self.ofs + 27 : self.ofs + 31] = int(
                time.perf_counter_ns() / DS5_EDGE_DELTA_TIME_NS
            ).to_bytes(8, byteorder="little", signed=False)[:4]

        #
        # Send report
        #
        # Sequence number
        if new_rep[self.ofs + 6] < 255:
            new_rep[self.ofs + 6] += 1
        else:
            new_rep[self.ofs + 6] = 0

        if self.use_bluetooth:
            sign_crc32_inplace(self.report, DS5_INPUT_CRC32_SEED)
        self.dev.send_input_report(self.report)
