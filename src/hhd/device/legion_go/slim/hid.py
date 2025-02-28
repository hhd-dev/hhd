import logging
from enum import Enum
from typing import Literal, Sequence

from hhd.controller import Event
from hhd.controller.lib.hid import Device
from hhd.controller.physical.hidraw import GenericGamepadHidraw

logger = logging.getLogger(__name__)

Controller = Literal["left", "right"]
RgbMode = Literal["solid", "pulse", "dynamic", "spiral"]


def to_bytes(s: str):
    return bytes.fromhex(s.replace(" ", ""))


def config_device(
    os: Literal["steamos", "windows"] | None,
    turbo: Literal["disabled", "2hz", "5hz", "8hz"] | None,
    touchpad: Literal["absolute", "relative"] | None,
    freq: Literal["125hz", "250hz", "500hz", "1000hz"] | None,
):
    out = []

    if os:
        # Disable OS autodetection
        out.append(to_bytes("040900"))

    if os == "steamos":
        # set OS type to steamos
        out.append(to_bytes("040a01"))
        # set touchpad config (steamos)
        if touchpad:
            out.append(bytes([0x06, 0x04, 0x01 if touchpad == "absolute" else 0x00]))
    elif os == "windows":
        # set OS type to windows
        out.append(to_bytes("040a00"))
        if touchpad:
            # set touchpad config (windows)
            out.append(bytes([0x06, 0x03, 0x01 if touchpad == "absolute" else 0x00]))

    # set turbo mode disable
    if turbo:
        out.append(bytes([0x12, 0x10, 0x00 if turbo != "disabled" else 0x01]))
        match turbo:
            case "2hz":
                out.append(to_bytes("120301"))
            case "5hz":
                out.append(to_bytes("120302"))
            case "8hz":
                out.append(to_bytes("120303"))
            case "disabled":
                # Disable all turbo mappings to avoid having them stick
                out.append(to_bytes("12020000000000"))

    match freq:
        case "125hz":
            out.append(to_bytes("041000"))
        case "250hz":
            out.append(to_bytes("041001"))
        case "500hz":
            out.append(to_bytes("041002"))
        case "1000hz":
            out.append(to_bytes("041003"))

    return out


def rgb_set_profile(
    profile: Literal[1, 2, 3],
    mode: RgbMode,
    red: int,
    green: int,
    blue: int,
    brightness: float = 1,
    speed: float = 1,
):
    assert profile in (1, 2, 3), f"Invalid profile '{profile}' selected."

    match mode:
        case "solid":
            r_mode = 0
        case "pulse":
            r_mode = 1
        case "dynamic":
            r_mode = 2
        case "spiral":
            r_mode = 3
        case _:
            assert False, f"Mode '{mode}' not supported. "

    r_brightness = min(max(int(64 * brightness), 0), 63)
    r_speed = min(max(int(64 * speed), 0), 63)

    return bytes(
        [
            0x10,
            profile + 2,
            r_mode,
            red,
            green,
            blue,
            r_brightness,
            r_speed,
        ]
    )


def rgb_load_profile(
    profile: Literal[1, 2, 3],
):
    return bytes([0x10, 0x02, profile])


def rgb_enable(enable: bool):
    r_enable = enable & 0x01
    return bytes([0x04, 0x06, r_enable])


def controller_factory_reset():
    return [
        # Reset XInput mapping
        to_bytes(
            "12010108038203000000000482040000000005820500000000068206000000000782070000000008820800000000098209000000000a820a0000000000000000"
        ),
        to_bytes(
            "120102080b820b000000000c820c000000000d820d000000000e820e000000000f820f0000000010821000000000128212000000001382130000000000000000"
        ),
        to_bytes(
            "120103081482140000000015821500000000168216000000001782170000000018821800000000198219000000001c821c000000001d821d0000000000000000"
        ),
        to_bytes(
            "12010402238223000000002482240000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
        ),
        # Enable touchpad
        to_bytes("040801"),
        # Disable touchpad vibration
        to_bytes("080300"),
        # Disable controller hibernation
        to_bytes("040400"),
        # Enable gyro
        to_bytes("040701"),
        to_bytes("040501"),  # hid imu for display rotation
        # Set controller to 500hz
        to_bytes("041002"),
        # todo...
    ]


def controller_legion_swap(enabled):
    return [to_bytes(f"0506 69 0401 {'02' if enabled else '01'} 01")]


def rgb_multi_load_settings(
    mode: RgbMode,
    profile: Literal[1, 2, 3],
    red: int,
    green: int,
    blue: int,
    brightness: float = 1,
    speed: float = 1,
    init: bool = True,
):
    base = [
        rgb_set_profile(profile, mode, red, green, blue, brightness, speed),
    ]
    # Always update
    if not init:
        return base

    return [
        rgb_enable(True),
        rgb_load_profile(profile),
        *base,
    ]


class RgbCallback:
    def __init__(self) -> None:
        self.prev_mode = None
        self.prev_event = None

    def __call__(self, dev: Device, events: Sequence[Event]):
        try:
            for ev in events:
                if ev["type"] != "led":
                    continue

                reps = None
                mode = None
                match ev["mode"]:
                    case "disabled":
                        pass
                    case "pulse":
                        mode = "pulse"
                    case "rainbow":
                        mode = "dynamic"
                    case "solid":
                        if ev["red"] or ev["green"] or ev["blue"]:
                            mode = "solid"
                        else:
                            # Disable if brightness is 0
                            mode = None
                    case "spiral":
                        mode = "spiral"
                    case _:
                        pass

                # On rgb modes such as the rainbow vomit, reiniting causes
                # a flicker, so we only update if the values have changed
                if self.prev_event:
                    pv = self.prev_event
                    if (
                        pv["mode"] == ev["mode"]
                        and pv["red"] == ev["red"]
                        and pv["green"] == ev["green"]
                        and pv["blue"] == ev["blue"]
                        and pv["brightness"] == ev["brightness"]
                        and pv["speed"] == ev["speed"]
                    ):
                        continue
                if mode:
                    reps = rgb_multi_load_settings(
                        mode,
                        0x03,
                        ev["red"],
                        ev["green"],
                        ev["blue"],
                        ev["brightness"],
                        ev["speed"],
                        self.prev_mode != mode,
                    )
                    self.prev_event = ev

                else:
                    reps = [rgb_enable(False)]
                
                # Only init sparingly, to speed up execution
                self.prev_mode = mode

                for r in reps:
                    dev.write(r)
        except Exception as e:
            logger.error(f"Error while setting RGB:\n{e}")


rgb_callback = RgbCallback()


class LegionHidraw(GenericGamepadHidraw):

    def with_settings(
        self,
        reset: bool,
        os: Literal["steamos", "windows"] | None = None,
        turbo: Literal["disabled", "2hz", "5hz", "8hz"] | None = None,
        touchpad: Literal["absolute", "relative"] | None = None,
        freq: Literal["125hz", "250hz", "500hz", "1000hz"] | None = None,
    ):
        self.reset = reset
        self.os = os
        self.turbo = turbo
        self.touchpad = touchpad
        self.freq = freq

        return self

    def open(self):
        out = super().open()
        if not out:
            return out
        if not self.dev:
            return out

        cmds = []

        if self.reset:
            logger.warning(f"Resetting controllers")
            cmds.extend(controller_factory_reset())

        cmds.extend(config_device(self.os, self.turbo, self.touchpad, self.freq))  # type: ignore

        for r in cmds:
            # logger.info(f"Sending command: {r.hex()}")
            self.dev.write(r)

        return out

    def close(self, exit: bool) -> bool:
        # Reset windows touchpad to relative to avoid windows having issues
        try:
            if (
                exit
                and self.dev
                and self.os == "windows"
                and self.touchpad == "absolute"
            ):
                self.dev.write(to_bytes("060300"))
        except Exception:
            pass

        return super().close(exit)


class LegionHidrawTs(GenericGamepadHidraw):
    def __init__(self, *args, motion: bool = True, **kwargs):
        super().__init__(*args, **kwargs)
        self.ts_count = 0
        self.motion = motion

    def produce(self, fds: Sequence[int]):
        evs = super().produce(fds)

        if self.motion and self.fd in fds:
            # If fd was readable, 8ms have passed
            self.ts_count += 8_000_000

            evs = [
                *evs,
                {"type": "axis", "code": "imu_ts", "value": self.ts_count},
            ]

        return evs
