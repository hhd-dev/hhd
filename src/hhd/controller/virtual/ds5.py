import sys
from threading import Lock, Condition
import time

from hhd.controller.base import Axis, Button

from ..base import ThreadedTransceiver, VirtualController
from ..uhid import UhidDevice
from .const import (
    DS5_EDGE_BUS,
    DS5_EDGE_COUNTRY,
    DS5_EDGE_DESCRIPTOR,
    DS5_EDGE_MAX_REPORT_FREQ,
    DS5_EDGE_MIN_REPORT_FREQ,
    DS5_EDGE_NAME,
    DS5_EDGE_PRODUCT,
    DS5_EDGE_VENDOR,
    DS5_EDGE_VERSION,
)

REPORT_MAX_DELAY = 1 / DS5_EDGE_MIN_REPORT_FREQ
REPORT_MIN_DELAY = 1 / DS5_EDGE_MAX_REPORT_FREQ
ANGL_RES = 1024
HID_LEN = 124


class DualSense5Edge(VirtualController, ThreadedTransceiver):
    def __init__(self) -> None:
        super().__init__()
        self.report = bytearray(HID_LEN)
        self.lock = Lock()
        self.cond = Condition(self.lock)

    def run(self):
        self.available = False
        dev = UhidDevice(
            vid=DS5_EDGE_VENDOR,
            pid=DS5_EDGE_PRODUCT,
            bus=DS5_EDGE_BUS,
            version=DS5_EDGE_VERSION,
            country=DS5_EDGE_COUNTRY,
            name=DS5_EDGE_NAME,
            report_descriptor=DS5_EDGE_DESCRIPTOR,
        )
        dev.send_create()

        last = time.perf_counter()
        woken = True
        while not self.should_exit:
            # Process queued events
            while ev := dev.read_event():
                match ev["type"]:
                    case "open":
                        self.available = True
                    case "close":
                        self.available = False

            # Sleep so that we have the minimum report rate, around 25hz
            # If we are woken by a commit, rerun the loop and sleep for the
            # minimum amount of time, which will approximate 1khz
            curr = time.perf_counter()
            if woken:
                sleep_time = REPORT_MIN_DELAY - (curr - last)
            else:
                sleep_time = REPORT_MAX_DELAY - (curr - last)

            if sleep_time > 0:
                with self.cond:
                    woken = not self.cond.wait(sleep_time)
                if woken:
                    continue
            last = curr

            with self.lock:
                self.report[0] = 1
                # self.report[28:32] = time.time_ns().to_bytes(4)
                dev.send_input_report(self.report)

            last = time.perf_counter()
        dev.send_destroy()

    def set_axis(self, key: Axis, val: float):
        type = None
        ofs = None
        match key:
            case Axis.GYRO_X:
                ofs = 16
                type = "gyro"
            case Axis.GYRO_Y:
                ofs = 18
                type = "gyro"
            case Axis.GYRO_Z:
                ofs = 20
                type = "gyro"
            case Axis.ACCEL_X:
                ofs = 22
                type = "accel"
            case Axis.ACCEL_Y:
                ofs = 24
                type = "accel"
            case Axis.ACCEL_Z:
                ofs = 26
                type = "accel"

        if not type or not ofs:
            return

        if type == "gyro":
            val = 1024 * val
        elif type == "accel":
            val = 8192 * val / 10
        val = int(val)

        with self.lock:
            self.report[ofs : ofs + 1] = int.to_bytes(
                val, length=2, byteorder=sys.byteorder, signed=True
            )

    def set_btn(self, key: Button, val: bool):
        pass

    def commit(self):
        with self.cond:
            self.cond.notify_all()
