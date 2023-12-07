import logging
from typing import Any, Literal, NamedTuple, Protocol, Sequence

from traitlets import default

from hhd.controller import Axis, Button, Consumer, Event, Producer
from hhd.controller.lib.common import AM, BM, decode_axis, get_button, hexify
from hhd.controller.lib.hid import Device, enumerate_unique

from ..base import can_read

MAX_REPORT_SIZE = 4096

logger = logging.getLogger(__name__)


class EventCallback(Protocol):
    def __call__(self, dev: Device, ev: Event) -> Any:
        pass


class GenericGamepadHidraw(Producer, Consumer):
    def __init__(
        self,
        vid: Sequence[int] = [],
        pid: Sequence[int] = [],
        manufacturer: Sequence[str] = [],
        product: Sequence[str] = [],
        usage_page: Sequence[int] = [],
        usage: Sequence[int] = [],
        btn_map: dict[int | None, dict[Button, BM]] = {},
        axis_map: dict[int | None, dict[Axis, AM]] = {},
        callback: EventCallback | None = None,
        report_size: int = MAX_REPORT_SIZE,
    ) -> None:
        self.vid = vid
        self.pid = pid
        self.manufacturer = manufacturer
        self.product = product
        self.usage_page = usage_page
        self.usage = usage
        self.report_size = report_size

        self.btn_map = btn_map
        self.axis_map = axis_map
        self.callback = callback

        self.path = None
        self.dev: Device | None = None
        self.fd = 0

        self.report = None

    def open(self) -> Sequence[int]:
        for d in enumerate_unique():
            if self.vid and d["vendor_id"] not in self.vid:
                continue
            if self.pid and d["product_id"] not in self.pid:
                continue
            if self.manufacturer and d["manufacturer_string"] not in self.manufacturer:
                continue
            if self.product and d["product_string"] not in self.product:
                continue
            if self.usage_page and d["usage_page"] not in self.usage_page:
                continue
            if self.usage and d["usage"] not in self.usage:
                continue
            self.path = d["path"]
            self.dev = Device(path=self.path)
            self.fd = self.dev.fd
            logger.info(
                f"Found device {hexify(d['vendor_id'])}:{hexify(d['product_id'])}:\n"
                + f"'{d['manufacturer_string']}': '{d['product_string']}' at {d['path']}"
            )
            self.report = None
            self.prev_btn = {}
            self.prev_axis = {}
            return [self.fd]

        err = f"Device with the following not found:\n"
        if self.vid:
            err += f"Vendor ID: {hexify(self.vid)}\n"
        if self.pid:
            err += f"Product ID: {hexify(self.pid)}\n"
        if self.manufacturer:
            err += f"Manufacturer: {self.manufacturer}\n"
        if self.product:
            err += f"Product: {self.product}\n"
        if self.usage_page:
            err += f"Usage Page: {hexify(self.usage_page)}\n"
        if self.usage:
            err += f"Usage: {hexify(self.usage)}\n"
        logger.error(err)
        return []

    def produce(self, fds: Sequence[int]) -> Sequence[Event]:
        # If we can not read return
        if not self.fd or not self.dev:
            return []
        rep = None

        # Throw away stale events
        while can_read(self.fd):
            rep = self.dev.read(self.report_size)

        # If we could not read (?) return
        if not rep:
            return []

        # If the report is the same as the previous one, return
        if self.report and self.report == rep:
            return []
        self.report = rep
        rep_id = rep[0]

        # Allow for devices with NULL reports
        if None in self.btn_map or None in self.axis_map:
            rep_id = None

        # Decode buttons
        out: list[Event] = []
        if rep_id in self.btn_map:
            for btn, map in self.btn_map[rep_id].items():
                val = get_button(rep, map)
                if btn in self.prev_btn and self.prev_btn[btn] == val:
                    continue
                self.prev_btn[btn] = val
                out.append({"type": "button", "code": btn, "value": val})

        # Decode Axis
        if rep_id in self.axis_map:
            for ax, map in self.axis_map[rep_id].items():
                val = decode_axis(rep, map)
                if ax in self.prev_axis and self.prev_axis[ax] == val:
                    continue
                self.prev_axis[ax] = val
                out.append({"type": "axis", "code": ax, "value": val})

        return out


__all__ = ["GenericGamepadHidraw", "BM", "AM"]
