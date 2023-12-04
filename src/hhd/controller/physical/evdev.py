import select
from typing import Sequence, TypeVar, cast

import evdev

from hhd.controller.base import Event

from ..base import Axis, Button, Producer

import logging

logger = logging.getLogger(__name__)


def B(b: str):
    return cast(int, getattr(evdev.ecodes, b))


A = TypeVar("A")


def to_map(b: dict[A, Sequence[int]]) -> dict[int, A]:
    out = {}
    for btn, seq in b.items():
        for s in seq:
            out[s] = btn
    return out


XBOX_BUTTON_MAP: dict[int, Button] = to_map(
    {
        # Gamepad
        "a": [B("BTN_A")],
        "b": [B("BTN_B")],
        "x": [B("BTN_X")],
        "y": [B("BTN_Y")],
        # Sticks
        "ls": [B("BTN_THUMBL")],
        "rs": [B("BTN_THUMBR")],
        # Bumpers
        "lb": [B("BTN_TL")],
        "rb": [B("BTN_TR")],
        # Select
        "start": [B("BTN_START")],
        "select": [B("BTN_SELECT")],
        # Misc
        "mode": [B("BTN_MODE")],
    }
)

XBOX_AXIS_MAP: dict[int, Axis] = to_map(
    {
        # Sticks
        # Values should range from -1 to 1
        "ls_x": [B("ABS_X")],
        "ls_y": [B("ABS_Y")],
        "rs_x": [B("ABS_RX")],
        "rs_y": [B("ABS_RY")],
        # Triggers
        # Values should range from -1 to 1
        "rt": [B("ABS_Z")],
        "lt": [B("ABS_RZ")],
        # Hat, implemented as axis. Either -1, 0, or 1
        "hat_x": [B("ABS_HAT0X")],
        "hat_y": [B("ABS_HAT0Y")],
    }
)

LGO_TOUCHPAD_BUTTON_MAP: dict[int, Button] = to_map(
    {
        "touchpad_touch": [B("BTN_TOOL_FINGER")],  # also BTN_TOUCH
        "touchpad_click": [B("BTN_TOOL_DOUBLETAP")],
    }
)

LGO_TOUCHPAD_AXIS_MAP: dict[int, Axis] = to_map(
    {
        "touchpad_x": [B("ABS_X")],  # also ABS_MT_POSITION_X
        "touchpad_y": [B("ABS_Y")],  # also ABS_MT_POSITION_Y
    }
)


class GenericGamepadEvdev(Producer):
    def __init__(
        self,
        vid: int | None,
        pid: int | None,
        name: str | None,
        btn_map: dict[int, Button] = XBOX_BUTTON_MAP,
        axis_map: dict[int, Axis] = XBOX_AXIS_MAP,
        aspect_ratio: float | None = None,
    ) -> None:
        self.vid = vid
        self.pid = pid
        self.name = name

        self.btn_map = btn_map
        self.axis_map = axis_map
        self.aspect_ratio = aspect_ratio

        self.dev: evdev.InputDevice | None = None
        self.fd = 0

    def open(self) -> Sequence[int]:
        for d in evdev.list_devices():
            dev = evdev.InputDevice(d)
            if self.vid and dev.info.vendor != self.vid:
                continue
            if self.pid and dev.info.product != self.pid:
                continue
            if self.name and dev.name != self.name:
                continue
            self.dev = dev
            self.dev.grab()
            self.ranges = {
                a: (i.min, i.max) for a, i in self.dev.capabilities()[B("EV_ABS")]  # type: ignore
            }
            self.fd = dev.fd
            self.started = True
            return [self.fd]

        logger.error(
            f"Device not found:\n{(self.pid if self.pid else 0):04X}:{(self.vid if self.vid else 0):04X} {self.name}"
        )
        return []

    def close(self, exit: bool) -> bool:
        if self.dev:
            self.dev.close()
            self.fd = 0
        return True

    def produce(self, fds: Sequence[int]) -> Sequence[Event]:
        if not self.dev or not self.fd in fds:
            return []

        out: list[Event] = []
        if self.started and self.aspect_ratio is not None:
            self.started = False
            out.append(
                {
                    "type": "configuration",
                    "conf": "touchpad_aspect_ratio",
                    "val": self.aspect_ratio,
                }
            )

        while select.select([self.fd], [], [], 0)[0]:
            for e in self.dev.read():
                if e.type == B("EV_KEY"):
                    if e.code in self.btn_map:
                        out.append(
                            {
                                "type": "button",
                                "button": self.btn_map[e.code],
                                "held": bool(e.value),
                            }
                        )
                elif e.type == B("EV_ABS"):
                    if e.code in self.axis_map:
                        # Normalize
                        val = e.value / abs(
                            self.ranges[e.code][1 if e.value >= 0 else 0]
                        )

                        out.append(
                            {
                                "type": "axis",
                                "axis": self.axis_map[e.code],
                                "val": val,
                            }
                        )
        return out
