import logging
from typing import Any, Literal, NamedTuple, Protocol, Sequence

from ..hid import Device, enumerate_unique
from ..base import Axis, Button, Consumer, Producer, Event

logger = logging.getLogger(__name__)


class BtnMap(NamedTuple):
    loc: int


class AxisMap(NamedTuple):
    loc: int
    width: int


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
            if self.vid and d["vendor_id"] not in d:
                continue
            if self.pid and d["product_id"] not in d:
                continue
            if self.manufacturer and d["manufacturer_string"] not in d:
                continue
            if self.product and d["product_string"] not in d:
                continue
            if self.usage_page and d["usage_page"] not in d:
                continue
            if self.usage and d["usage"] not in d:
                continue
            self.path = d["path"]
            self.dev = Device(path=self.path)
            self.fd = self.dev.fd
            return [self.fd]

        err = f"Device with the following not found:\n"
        if self.vid:
            err += f"Vendor ID: {self.vid}\n"
        if self.pid:
            err += f"Product ID: {self.pid}\n"
        if self.manufacturer:
            err += f"Manufacturer: {self.manufacturer}\n"
        if self.product:
            err += f"Product: {self.product}\n"
        if self.usage_page:
            err += f"Usage Page: {self.usage_page}\n"
        if self.usage:
            err += f"Usage: {self.usage}\n"
        logger.error(err)
        return []
