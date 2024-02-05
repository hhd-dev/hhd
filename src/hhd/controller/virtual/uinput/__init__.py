import logging
import time
from typing import Sequence, cast

from evdev import UInput

from hhd.controller.base import Consumer, Event, Producer, can_read
from hhd.controller.const import Axis, Button

from .const import *

logger = logging.getLogger(__name__)


# Monkey patch Uinput device to avoid issues
# _find_device() may crash when controllers
# disconnect. We dont use the produced device anyway.
def _patch(*args, **kwargs):
    pass


UInput._find_device = _patch


class UInputDevice(Consumer, Producer):
    def __init__(
        self,
        capabilities=GAMEPAD_CAPABILITIES,
        btn_map: dict[Button, int] = GAMEPAD_BUTTON_MAP,
        axis_map: dict[Axis, AX] = GAMEPAD_AXIS_MAP,
        vid: int = HHD_VID,
        pid: int = HHD_PID_GAMEPAD,
        name: str = "Handheld Daemon Controller",
        phys: str = "phys-hhd-gamepad",
        output_imu_timestamps: bool = False,
        output_timestamps: bool = False,
    ) -> None:
        self.capabilities = capabilities
        self.btn_map = btn_map
        self.axis_map = axis_map
        self.dev = None
        self.name = name
        self.vid = vid
        self.pid = pid
        self.phys = phys
        self.output_imu_timestamps = output_imu_timestamps
        self.output_timestamps = output_timestamps
        self.ofs = 0
        self.sys_ofs = 0

        self.rumble: Event | None = None

    def open(self) -> Sequence[int]:
        logger.info(f"Opening virtual device '{self.name}'.")
        self.dev = UInput(
            events=self.capabilities,
            name=self.name,
            vendor=self.vid,
            product=self.pid,
            phys=self.phys,
        )
        self.touchpad_aspect = 1
        self.touch_id = 1
        self.fd = self.dev.fd
        return [self.fd]

    def close(self, exit: bool) -> bool:
        if self.dev:
            self.dev.close()
        self.dev = None
        self.input = None
        self.fd = None
        return True

    def consume(self, events: Sequence[Event]):
        if not self.dev:
            return

        wrote = False
        for ev in events:
            match ev["type"]:
                case "axis":
                    if ev["code"] in self.axis_map:
                        ax = self.axis_map[ev["code"]]
                        if ev["code"] == "touchpad_x":
                            val = int(
                                self.touchpad_aspect
                                * (ax.scale * ev["value"] + ax.offset)
                            )
                        else:
                            val = int(ax.scale * ev["value"] + ax.offset)
                        if ax.bounds:
                            val = min(max(val, ax.bounds[0]), ax.bounds[1])
                        self.dev.write(B("EV_ABS"), ax.id, val)
                        wrote = True

                        if ev["code"] == "touchpad_x":
                            self.dev.write(B("EV_ABS"), B("ABS_MT_POSITION_X"), val)
                        elif ev["code"] == "touchpad_y":
                            self.dev.write(B("EV_ABS"), B("ABS_MT_POSITION_Y"), val)

                    elif self.output_imu_timestamps and ev["code"] in (
                        "accel_ts",
                        "gyro_ts",
                    ):
                        # We have timestamps with ns accuracy.
                        # Evdev expects us accuracy
                        ts = ev["value"] // 1000
                        # Use an ofs to avoid overflowing
                        if ts > self.ofs + 2**30:
                            self.ofs = ts
                        ts -= self.ofs
                        self.dev.write(B("EV_MSC"), B("MSC_TIMESTAMP"), ts)
                        wrote = True
                case "button":
                    if ev["code"] in self.btn_map:
                        if ev["code"] == "touchpad_touch":
                            self.dev.write(
                                B("EV_ABS"),
                                B("ABS_MT_TRACKING_ID"),
                                self.touch_id if ev["value"] else -1,
                            )
                            self.dev.write(
                                B("EV_KEY"),
                                B("BTN_TOOL_FINGER"),
                                1 if ev["value"] else 0,
                            )
                            self.touch_id += 1
                            if self.touch_id > 500:
                                self.touch_id = 1
                        self.dev.write(
                            B("EV_KEY"),
                            self.btn_map[ev["code"]],
                            1 if ev["value"] else 0,
                        )
                        wrote = True

                case "configuration":
                    if ev["code"] == "touchpad_aspect_ratio":
                        self.touchpad_aspect = float(ev["value"])

        if wrote and self.output_timestamps:
            # We have timestamps with ns accuracy.
            # Evdev expects us accuracy
            ts = time.perf_counter_ns() // 1000
            # Use an ofs to avoid overflowing
            if ts > self.ofs + 2**30:
                self.ofs = ts
            ts -= self.ofs
            self.dev.write(B("EV_MSC"), B("MSC_TIMESTAMP"), ts)

        if wrote:
            self.dev.syn()

    def produce(self, fds: Sequence[int]) -> Sequence[Event]:
        if not self.fd or not self.fd in fds or not self.dev:
            return []

        out: Sequence[Event] = []

        while can_read(self.fd):
            for ev in self.dev.read():
                if ev.type == B("EV_MSC") and ev.code == B("MSC_TIMESTAMP"):
                    # Skip timestamp feedback
                    # TODO: Figure out why it feedbacks
                    pass
                elif ev.type == B("EV_UINPUT"):
                    if ev.code == B("UI_FF_UPLOAD"):
                        # Keep uploaded effect to apply on input
                        upload = self.dev.begin_upload(ev.value)
                        if upload.effect.type == B("FF_RUMBLE"):
                            data = upload.effect.u.ff_rumble_effect

                            self.rumble = {
                                "type": "rumble",
                                "code": "main",
                                "weak_magnitude": data.weak_magnitude / 0xFFFF,
                                "strong_magnitude": data.strong_magnitude / 0xFFFF,
                            }
                        self.dev.end_upload(upload)
                    elif ev.code == B("UI_FF_ERASE"):
                        # Ignore erase events
                        erase = self.dev.begin_erase(ev.value)
                        erase.retval = 0
                        ev.end_erase(erase)
                elif ev.type == B("EV_FF") and ev.value:
                    if self.rumble:
                        out.append(self.rumble)
                    else:
                        logger.warn(
                            f"Rumble requested but a rumble effect has not been uploaded."
                        )
                elif ev.type == B("EV_FF") and not ev.value:
                    out.append(
                        {
                            "type": "rumble",
                            "code": "main",
                            "weak_magnitude": 0,
                            "strong_magnitude": 0,
                        }
                    )
                else:
                    logger.info(f"Controller ev received unhandled event:\n{ev}")

        return out
