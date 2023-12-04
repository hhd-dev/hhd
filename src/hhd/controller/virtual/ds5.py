import sys
from threading import Lock, Condition
import time
from typing import Sequence

from hhd.controller.base import Axis, Button, Event

from ..base import Consumer, Producer
from ..uhid import UhidDevice
from .const import (
    DS5_EDGE_BUS,
    DS5_EDGE_COUNTRY,
    DS5_EDGE_DESCRIPTOR,
    DS5_EDGE_MAX_REPORT_FREQ,
    DS5_EDGE_MIN_REPORT_FREQ,
    DS5_EDGE_NAME,
    DS5_EDGE_PRODUCT,
    DS5_EDGE_REPORT_USB_BASE,
    DS5_EDGE_STOCK_REPORTS,
    DS5_EDGE_VENDOR,
    DS5_EDGE_VERSION,
    DS5_EDGE_DELTA_TIME,
)

REPORT_MAX_DELAY = 1 / DS5_EDGE_MIN_REPORT_FREQ
REPORT_MIN_DELAY = 1 / DS5_EDGE_MAX_REPORT_FREQ
ANGL_RES = 1024


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
        for ev in events:
            match ev["type"]:
                case "axis":
                    type = None
                    ofs = None
                    match ev["axis"]:
                        case "gyro_x":
                            ofs = 16
                            type = "gyro"
                        case "gyro_y":
                            ofs = 18
                            type = "gyro"
                        case "gyro_z":
                            ofs = 20
                            type = "gyro"
                        case "accel_x":
                            ofs = 22
                            type = "accel"
                        case "accel_y":
                            ofs = 24
                            type = "accel"
                        case "accel_z":
                            ofs = 26
                            type = "accel"

                    if not type or not ofs:
                        continue

                    val = ev["val"]
                    # TODO: Figure out the correct normalization values
                    # For now, this does the inverse scaling of the legion go's imu data
                    if type == "gyro":
                        val = 5729.6 * val
                    elif type == "accel":
                        val = 10.19716 * val
                    val = int(val)

                    try:
                        self.report[ofs : ofs + 2] = int.to_bytes(
                            val, length=2, byteorder=sys.byteorder, signed=True
                        )
                    except:
                        # TODO: Debug
                        pass

        # Send report
        self.report[28:32] = int(
            (time.time() - self.start) * DS5_EDGE_DELTA_TIME
        ).to_bytes(4, byteorder=sys.byteorder, signed=False)
        self.dev.send_input_report(self.report)
