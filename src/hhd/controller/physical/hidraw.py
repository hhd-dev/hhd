import logging
from typing import Any, Literal, NamedTuple, Protocol, Sequence

from hhd.controller.lib.hid import Device, enumerate_unique
from hhd.controller import Axis, Button, Consumer, Producer, Event

logger = logging.getLogger(__name__)


class BtnMap(NamedTuple):
    loc: int


class AxisMap(NamedTuple):
    loc: int
    width: int
    signed: bool


def BM(loc: int):
    return BtnMap(loc)


def AM(loc: int, width: int, signed: bool):
    return AxisMap(loc, width, signed)


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
        btn_map: dict[int, Button] = {},
        axis_map: dict[AxisMap, Axis] = {},
        callback: EventCallback | None = None,
    ) -> None:
        self.vid = vid
        self.pid = pid
        self.manufacturer = manufacturer
        self.product = product
        self.usage_page = usage_page
        self.usage = usage

        self.btn_map = btn_map
        self.axis_map = axis_map
        self.callback = callback

        self.path = None
        self.dev: Device | None = None
        self.fd = 0

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


def hexify(d: int | Sequence[int]):
    if isinstance(d, int):
        return f"0x{d:04x}"
    else:
        return [hexify(v) for v in d]


def pretty_print(dev: dict[str, str | int | bytes]):
    out = ""
    for n, v in dev.items():
        if isinstance(v, int):
            out += f"{n}: {hexify(v)}\n"
        elif isinstance(v, str):
            out += f"{n}: '{v}'\n"
        else:
            out += f"{n}: {v}\n"
    return out


__all__ = ["GenericGamepadHidraw", "BM", "AM"]
