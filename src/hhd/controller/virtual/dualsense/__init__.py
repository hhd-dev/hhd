import logging
import time
from collections import defaultdict
from typing import Literal, NamedTuple, Sequence, cast

from hhd.controller import (
    Consumer,
    Event,
    Producer,
    TouchpadCorrectionType,
    correct_touchpad,
)
from hhd.controller.lib.common import encode_axis, set_button
from hhd.controller.lib.uhid import BUS_BLUETOOTH, BUS_USB, UhidDevice

from .const import (
    DS5_BT_AXIS_MAP,
    DS5_BT_BTN_MAP,
    DS5_EDGE_COUNTRY,
    DS5_EDGE_DELTA_TIME_NS,
    DS5_EDGE_DESCRIPTOR_BT,
    DS5_EDGE_DESCRIPTOR_USB,
    DS5_EDGE_MAX_REPORT_FREQ,
    DS5_EDGE_MIN_REPORT_FREQ,
    DS5_EDGE_NAME,
    DS5_NAME,
    DS5_EDGE_PRODUCT,
    DS5_EDGE_STOCK_REPORTS,
    DS5_EDGE_TOUCH_HEIGHT,
    DS5_EDGE_TOUCH_WIDTH,
    DS5_EDGE_VERSION,
    DS5_FEATURE_CRC32_SEED,
    DS5_INPUT_CRC32_SEED,
    DS5_INPUT_REPORT_BT_OFS,
    DS5_INPUT_REPORT_USB_OFS,
    DS5_PRODUCT,
    DS5_USB_AXIS_MAP,
    DS5_USB_BTN_MAP,
    DS5_VENDOR,
    patch_dpad_val,
    prefill_ds5_report,
    sign_crc32_append,
    sign_crc32_inplace,
)

REPORT_MAX_DELAY = 1 / DS5_EDGE_MIN_REPORT_FREQ
REPORT_MIN_DELAY = 1 / DS5_EDGE_MAX_REPORT_FREQ
DS5_EDGE_MIN_TIMESTAMP_INTERVAL = 1500

logger = logging.getLogger(__name__)


class Dualsense(Producer, Consumer):
    def __init__(
        self,
        touchpad_method: TouchpadCorrectionType = "crop_end",
        edge_mode: bool = True,
        use_bluetooth: bool = True,
        fake_timestamps: bool = False,
        enable_touchpad: bool = True,
        enable_rgb: bool = True,
        sync_gyro: bool = False,
        paddles_to_clicks: bool = False,
    ) -> None:
        self.available = False
        self.report = None
        self.dev = None
        self.start = 0
        self.use_bluetooth = use_bluetooth
        self.edge_mode = edge_mode
        self.fake_timestamps = fake_timestamps
        self.touchpad_method: TouchpadCorrectionType = touchpad_method
        self.enable_touchpad = enable_touchpad
        self.enable_rgb = enable_rgb
        self.sync_gyro = sync_gyro
        self.paddles_to_clicks = paddles_to_clicks

        self.ofs = (
            DS5_INPUT_REPORT_BT_OFS if use_bluetooth else DS5_INPUT_REPORT_USB_OFS
        )
        self.axis_map = DS5_BT_AXIS_MAP if use_bluetooth else DS5_USB_AXIS_MAP
        self.btn_map = DS5_BT_BTN_MAP if use_bluetooth else DS5_USB_BTN_MAP

    def open(self) -> Sequence[int]:
        self.available = False
        self.report = bytearray(prefill_ds5_report(self.use_bluetooth))
        self.dev = UhidDevice(
            vid=DS5_VENDOR,
            pid=DS5_EDGE_PRODUCT if self.edge_mode else DS5_PRODUCT,
            bus=BUS_BLUETOOTH if self.use_bluetooth else BUS_USB,
            version=DS5_EDGE_VERSION,
            country=DS5_EDGE_COUNTRY,
            name=DS5_EDGE_NAME if self.edge_mode else DS5_NAME,
            report_descriptor=(
                DS5_EDGE_DESCRIPTOR_BT
                if self.use_bluetooth
                else DS5_EDGE_DESCRIPTOR_USB
            ),
        )

        self.touch_correction = correct_touchpad(
            DS5_EDGE_TOUCH_WIDTH, DS5_EDGE_TOUCH_HEIGHT, 1, self.touchpad_method
        )

        self.state: dict = defaultdict(lambda: 0)
        self.rumble = False
        self.touchpad_touch = False
        self.touchpad_down = time.perf_counter()
        self.start = time.perf_counter_ns()
        self.fd = self.dev.open()

        logger.info(
            f"Starting '{(DS5_EDGE_NAME if self.edge_mode else DS5_NAME).decode()}'."
        )
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

                    flag0 = rep[1]
                    flag1 = rep[2]
                    flag2 = rep[39]
                    if self.enable_rgb and (
                        flag1 & 4
                    ):  # DS_OUTPUT_VALID_FLAG1_LIGHTBAR_CONTROL_ENABLE
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

                        # Crunch lower values since steam is bugged
                        if red < 3 and green < 3 and blue < 3:
                            red = 0
                            green = 0
                            blue = 0

                        out.append(
                            {
                                "type": "led",
                                "code": "main",
                                "mode": "solid",
                                # "brightness": led_brightness / 63
                                # if led_brightness
                                # else 1,
                                "brightness": 1,
                                "speed": 0,
                                "red": red,
                                "blue": blue,
                                "green": green,
                            }
                        )
                    # elif (rep[39] & 2) and (rep[42] & 2):
                    #     # flag2 is DS_OUTPUT_VALID_FLAG2_LIGHTBAR_SETUP_CONTROL_ENABLE
                    #     # lightbar_setup is DS_OUTPUT_LIGHTBAR_SETUP_LIGHT_OUT
                    #     # FIXME: Disable for now to avoid hid_playstation messing
                    #     # with the leds
                    #     out.append(
                    #         {
                    #             "type": "led",
                    #             "code": "main",
                    #             "mode": "disable",
                    #             "brightness": 0,
                    #             "speed": 0,
                    #             "red": 0,
                    #             "blue": 0,
                    #             "green": 0,
                    #         }
                    #     )
                    #     pass

                    # Rumble
                    # Flag 1
                    # Death stranding uses 0x40 to turn on vibration
                    # SDL uses 0x02 to disable audio haptics
                    # old version used flag0 & 0x02
                    # Initial compatibility rumble is flag0 0x01
                    # Improved is flag2 0x04
                    if flag0 & 0x01 or flag2 & 0x04:
                        right = rep[3]
                        left = rep[4]

                        # If vibration mode is in flag0 use different scale
                        scale = 2 if flag0 & 0x01 else 1

                        out.append(
                            {
                                "type": "rumble",
                                "code": "main",
                                # For some reason goes to 127
                                "strong_magnitude": left / 255 * scale,
                                "weak_magnitude": right / 255 * scale,
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
        # To fix gyro to mouse in latest steam
        # only send updates when gyro sends a timestamp
        send = not self.sync_gyro

        new_rep = bytearray(self.report)
        for ev in events:
            match ev["type"]:
                case "axis":
                    if not self.enable_touchpad and ev["code"].startswith("touchpad"):
                        continue
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
                            send = True
                            new_rep[self.ofs + 27 : self.ofs + 31] = int(
                                ev["value"] / DS5_EDGE_DELTA_TIME_NS
                            ).to_bytes(8, byteorder="little", signed=False)[:4]
                case "button":
                    if not self.enable_touchpad and ev["code"].startswith("touchpad"):
                        continue
                    if self.paddles_to_clicks and (ev["code"] == "extra_l1"):
                        # Place finger on correct place and click
                        new_rep[self.ofs + 33] = 0x80
                        new_rep[self.ofs + 34] = 0x01
                        new_rep[self.ofs + 35] = 0x20
                        # Replace code with click
                        ev = {**ev, "code": "touchpad_left"}
                    if self.paddles_to_clicks and (ev["code"] == "extra_r1"):
                        # Place finger on correct place and click
                        new_rep[self.ofs + 33] = 0x00
                        new_rep[self.ofs + 34] = 0x06
                        new_rep[self.ofs + 35] = 0x20
                        # Replace code with click
                        ev = {**ev, "code": "touchpad_left"}

                    if ev["code"] in self.btn_map:
                        set_button(new_rep, self.btn_map[ev["code"]], ev["value"])

                    # Fix touchpad click requiring touch
                    if ev["code"] == "touchpad_touch":
                        self.touchpad_touch = ev["value"]
                    if ev["code"] == "touchpad_left":
                        set_button(
                            new_rep,
                            self.btn_map["touchpad_touch"],
                            ev["value"] or self.touchpad_touch,
                        )
                    # Also add right click
                    if ev["code"] == "touchpad_right":
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
        # Caching can cause issues since receivers expect reports
        # at least a couple of times per second
        # if new_rep == self.report and not self.fake_timestamps:
        #     return
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
        if send:
            self.dev.send_input_report(self.report)
