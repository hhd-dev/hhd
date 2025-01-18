import logging
import re
from typing import Any, Literal, NamedTuple, Protocol, Sequence

from hhd.controller import (
    Axis,
    Button,
    Configuration,
    Consumer,
    Event,
    Producer,
    can_read,
)
from hhd.controller.base import Event
from hhd.controller.lib.common import (
    AM,
    BM,
    CM,
    decode_axis,
    decode_config,
    get_button,
    hexify,
    matches_patterns,
)
from hhd.controller.lib.hid import MAX_REPORT_SIZE, Device, enumerate_unique

logger = logging.getLogger(__name__)


class EventCallback(Protocol):
    def __call__(self, dev: Device, events: Sequence[Event]) -> Any:
        pass


class GenericGamepadHidraw(Producer, Consumer):
    def __init__(
        self,
        vid: Sequence[int] = [],
        pid: Sequence[int] = [],
        manufacturer: Sequence[str | re.Pattern] = [],
        product: Sequence[str | re.Pattern] = [],
        usage_page: Sequence[int] = [],
        usage: Sequence[int] = [],
        interface: int | None = None,
        btn_map: dict[int | None, dict[Button, BM]] = {},
        axis_map: dict[int | None, dict[Axis, AM]] = {},
        config_map: dict[int | None, dict[Configuration, CM]] = {},
        callback: EventCallback | None = None,
        report_size: int = MAX_REPORT_SIZE,
        required: bool = True,
        lossless: bool = True,
    ) -> None:
        self.vid = vid
        self.pid = pid
        self.manufacturer = manufacturer
        self.product = product
        self.usage_page = usage_page
        self.usage = usage
        self.interface = interface
        self.report_size = report_size

        self.btn_map = btn_map
        self.axis_map = axis_map
        self.config_map = config_map
        self.callback = callback
        self.required = required
        self.lossless = lossless

        self.path = None
        self.dev: Device | None = None
        self.fd = 0

        self.report = None

    def open(self) -> Sequence[int]:
        for d in enumerate_unique():
            if not matches_patterns(d["vendor_id"], self.vid):
                continue
            if not matches_patterns(d["product_id"], self.pid):
                continue
            if not matches_patterns(d["manufacturer_string"], self.manufacturer):
                continue
            if not matches_patterns(d["product_string"], self.product):
                continue
            if not matches_patterns(d["usage_page"], self.usage_page):
                continue
            if not matches_patterns(d["usage"], self.usage):
                continue
            if (
                self.interface is not None
                and d.get("interface_number", None) != self.interface
            ):
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
            self.prev_config = {}
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
        if self.required:
            raise RuntimeError()
        return []

    def produce(self, fds: Sequence[int]) -> Sequence[Event]:
        # If we can not read return
        if not self.fd or self.fd not in fds or not self.dev:
            return []
        rep = None

        if self.lossless:
            # Keep all events
            rep = self.dev.read(self.report_size)
        else:
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
        rep_id = rep[2] if len(rep) > 2 else None

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

        # Decode
        if rep_id in self.config_map:
            for cnf, map in self.config_map[rep_id].items():
                val = decode_config(rep, map)
                if cnf in self.prev_config and self.prev_config[cnf] == val:
                    continue
                self.prev_config[cnf] = val
                out.append({"type": "configuration", "code": cnf, "value": val})
        return out

    def consume(self, events: Sequence[Event]):
        if self.callback and self.dev:
            self.callback(self.dev, events)

    def close(self, exit: bool) -> bool:
        if self.dev:
            self.dev.close()
            self.dev = None
        return True


__all__ = ["GenericGamepadHidraw", "BM", "AM"]
