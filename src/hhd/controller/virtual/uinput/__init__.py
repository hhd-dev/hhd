import logging
from typing import Sequence, cast

import evdev
from evdev import UInput, AbsInfo

from hhd.controller import Axis, Button, Consumer, Producer
from hhd.controller.base import Event, can_read

from .const import *

logger = logging.getLogger(__name__)


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
    ) -> None:
        self.capabilities = capabilities
        self.btn_map = btn_map
        self.axis_map = axis_map
        self.dev = None
        self.name = name
        self.vid = vid
        self.pid = pid
        self.phys = phys

    def open(self) -> Sequence[int]:
        logger.info(f"Opening virtual device '{self.name}'")
        self.dev = UInput(
            events=self.capabilities,
            name=self.name,
            vendor=self.vid,
            product=self.pid,
            phys=self.phys,
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
                    if ev["code"] in self.axis_map:
                        ax = self.axis_map[ev["code"]]
                        val = int(ax.scale * ev["value"] + ax.offset)
                        self.dev.write(B("EV_ABS"), ax.id, val)
                case "button":
                    if ev["code"] in self.btn_map:
                        self.dev.write(
                            B("EV_KEY"),
                            self.btn_map[ev["code"]],
                            1 if ev["value"] else 0,
                        )
        self.dev.syn()
