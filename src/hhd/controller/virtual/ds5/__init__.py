import sys
import time
from typing import Sequence

from hhd.controller import Axis, Button, Consumer, Event, Producer
from hhd.controller.lib.common import AM, BM, decode_axis, encode_axis, set_button
from hhd.controller.lib.uhid import UhidDevice

from .const import (
    DS5_AXIS_MAP,
    DS5_BUTTON_MAP,
    DS5_EDGE_BUS,
    DS5_EDGE_COUNTRY,
    DS5_EDGE_DELTA_TIME,
    DS5_EDGE_DESCRIPTOR,
    DS5_EDGE_MAX_REPORT_FREQ,
    DS5_EDGE_MIN_REPORT_FREQ,
    DS5_EDGE_NAME,
    DS5_EDGE_PRODUCT,
    DS5_EDGE_REPORT_USB_BASE,
    DS5_EDGE_STOCK_REPORTS,
    DS5_EDGE_VENDOR,
    DS5_EDGE_VERSION,
)

REPORT_MAX_DELAY = 1 / DS5_EDGE_MIN_REPORT_FREQ
REPORT_MIN_DELAY = 1 / DS5_EDGE_MAX_REPORT_FREQ


class DualSense5Edge(Producer, Consumer):
    def __init__(self) -> None:
        self.available = False
        self.report = None
        self.dev = None
        self.start = 0

    def open(self) -> Sequence[int]:
        self.available = False
        self.report = bytearray(DS5_EDGE_REPORT_USB_BASE)
        self.dev = UhidDevice(
            vid=DS5_EDGE_VENDOR,
            pid=DS5_EDGE_PRODUCT,
            bus=DS5_EDGE_BUS,
            version=DS5_EDGE_VERSION,
            country=DS5_EDGE_COUNTRY,
            name=DS5_EDGE_NAME,
            report_descriptor=DS5_EDGE_DESCRIPTOR,
        )
        self.start = time.time()
        self.fd = self.dev.open()
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
        assert self.dev
        while ev := self.dev.read_event():
            match ev["type"]:
                case "open":
                    self.available = True
                case "close":
                    self.available = False
                case "get_report":
                    if ev["rnum"] in DS5_EDGE_STOCK_REPORTS:
                        self.dev.send_get_report_reply(
                            ev["id"], 0, DS5_EDGE_STOCK_REPORTS[ev["rnum"]]
                        )

        return []

    def consume(self, events: Sequence[Event]):
        assert self.dev and self.report

        new_rep = bytearray(self.report)
        for ev in events:
            match ev["type"]:
                case "axis":
                    if ev["code"] in DS5_AXIS_MAP:
                        encode_axis(new_rep, DS5_AXIS_MAP[ev["code"]], ev["value"])
                case "button":
                    if ev["code"] in DS5_BUTTON_MAP:
                        set_button(new_rep, DS5_BUTTON_MAP[ev["code"]], ev["value"])
        if new_rep == self.report:
            return
        self.report = new_rep

        # Send report
        new_rep[28:32] = int((time.time() - self.start) * DS5_EDGE_DELTA_TIME).to_bytes(
            4, byteorder=sys.byteorder, signed=False
        )
        self.dev.send_input_report(self.report)
