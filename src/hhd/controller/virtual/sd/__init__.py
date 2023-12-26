import logging
import time
from collections import defaultdict
from typing import Sequence

from hhd.controller import Consumer, Event, Producer
from hhd.controller.lib.uhid import UhidDevice, BUS_USB

from .const import (
    SDCONT_VENDOR,
    SDCONT_PRODUCT,
    SDCONT_VERSION,
    SDCONT_COUNTRY,
    SDCONT_NAME,
    SDCONT_DESCRIPTOR,
)

logger = logging.getLogger(__name__)


class SteamdeckOLEDController(Producer, Consumer):
    def __init__(
        self,
    ) -> None:
        self.available = False
        self.report = None
        self.dev = None
        self.start = 0

    def open(self) -> Sequence[int]:
        self.available = False
        self.report = bytearray([64] + [0 for _ in range(64)])
        self.dev = UhidDevice(
            vid=SDCONT_VENDOR,
            pid=SDCONT_PRODUCT,
            bus=BUS_USB,
            version=SDCONT_VERSION,
            country=SDCONT_COUNTRY,
            name=SDCONT_NAME,
            report_descriptor=SDCONT_DESCRIPTOR,
        )

        self.state: dict = defaultdict(lambda: 0)
        self.rumble = False
        self.touchpad_touch = False
        self.start = time.perf_counter_ns()
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
        return []

    def consume(self, events: Sequence[Event]):
        pass
