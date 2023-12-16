import logging
from typing import Sequence, cast

import evdev
from evdev import UInput

from hhd.controller import Axis, Button, Consumer, Producer
from hhd.controller.base import Event, can_read


def B(b: str):
    return cast(int, getattr(evdev.ecodes, b))


logger = logging.getLogger(__name__)

GAMEPAD_BTN_CAPABILITIES = {
    B("EV_KEY"): [
        B("BTN_TL"),
        B("BTN_TR"),
        B("BTN_SELECT"),
        B("BTN_START"),
        B("BTN_MODE"),
        B("BTN_THUMBL"),
        B("BTN_THUMBR"),
        B("BTN_A"),
        B("BTN_B"),
        B("BTN_X"),
        B("BTN_Y"),
        B("BTN_MODE"),
        B("BTN_TRIGGER_HAPPY1"),
        B("BTN_TRIGGER_HAPPY2"),
        B("BTN_TRIGGER_HAPPY3"),
        B("BTN_TRIGGER_HAPPY4"),
        B("BTN_TRIGGER_HAPPY5"),
        B("BTN_TRIGGER_HAPPY6"),
    ]
}
STANDARD_BUTTON_MAP: dict[Button, int] = {
    # Gamepad
    "a": B("BTN_A"),
    "b": B("BTN_B"),
    "x": B("BTN_X"),
    "y": B("BTN_Y"),
    # Sticks
    "ls": B("BTN_THUMBL"),
    "rs": B("BTN_THUMBR"),
    # Bumpers
    "lb": B("BTN_TL"),
    "rb": B("BTN_TR"),
    # Select
    "start": B("BTN_START"),
    "select": B("BTN_SELECT"),
    # Misc
    "mode": B("BTN_MODE"),
    # Back buttons
    "extra_l1": B("BTN_TRIGGER_HAPPY1"),
    "extra_l2": B("BTN_TRIGGER_HAPPY2"),
    "extra_l3": B("BTN_TRIGGER_HAPPY5"),
    "extra_r1": B("BTN_TRIGGER_HAPPY3"),
    "extra_r2": B("BTN_TRIGGER_HAPPY4"),
    "extra_r3": B("BTN_TRIGGER_HAPPY6"),
}


class UInputDevice(Consumer, Producer):
    def __init__(
        self,
        capabilities=GAMEPAD_BTN_CAPABILITIES,
        btn_map: dict[Button, int] = STANDARD_BUTTON_MAP,
        axis_map: dict[Axis, int] = {},
        vid: int = 2,
        pid: int = 2,
        name: str = "HHD Shortcuts Device",
    ) -> None:
        self.capabilities = capabilities
        self.btn_map = btn_map
        self.axis_map = axis_map
        self.dev = None
        self.name = name
        self.vid = vid
        self.pid = pid

    def open(self) -> Sequence[int]:
        logger.info(f"Opening virtual device '{self.name}'")
        self.dev = UInput(
            events=self.capabilities, name=self.name, vendor=self.vid, product=self.pid
        )
        self.fd = self.dev.fd
        return [self.fd]

    def close(self, exit: bool) -> bool:
        if self.dev:
            self.dev.close()
        self.input = None
        self.fd = None
        return True

    def consume(self, events: Sequence[Event]):
        if not self.dev:
            return
        for ev in events:
            match ev["type"]:
                case "axis":
                    # if ev["code"] in self.axis_map:
                    #     self.dev.write(B("EV_ABS"), self.axis_map[ev["code"]], ev['value'])
                    # TODO: figure out normalization
                    if ev['value']:
                        logger.error(f"Outputing axis not supported yet. Event:\n{ev}")
                case "button":
                    if ev["code"] in self.btn_map:
                        self.dev.write(
                            B("EV_KEY"),
                            self.btn_map[ev["code"]],
                            1 if ev["value"] else 0,
                        )
        self.dev.syn()
