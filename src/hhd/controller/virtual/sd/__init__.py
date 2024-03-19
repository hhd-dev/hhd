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


def trim(rep: bytes):
    if not rep:
        return rep
    idx = len(rep) - 1
    while idx > 0 and rep[idx] == 0x00:
        idx -= 1
    return rep[: idx + 1]


def pad(rep):
    return bytes(rep) + bytes([0 for _ in range(64 - len(rep))])


class SteamdeckOLEDController(Producer, Consumer):
    def __init__(
        self,
    ) -> None:
        self.available = False
        self.report = None
        self.dev = None
        self.start = 0
        self.last_rep = None

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
        if not self.fd or not self.dev or self.fd not in fds:
            return []

        # Process queued events
        out: Sequence[Event] = []
        assert self.dev
        while ev := self.dev.read_event():
            match ev["type"]:
                case "open":
                    logger.info(f"OPENED")
                case "close":
                    logger.info(f"CLOSED")
                case "get_report":
                    match self.last_rep:
                        case 0xAE:
                            rep = bytes(
                                [
                                    0x00,
                                    0xAE,
                                    0x15,
                                    0x01,
                                    *[0x10 for _ in range(15)],
                                ]
                            )
                        case _:
                            rep = bytes([])
                    self.dev.send_get_report_reply(ev["id"], 0, pad(rep))
                    logger.info(
                        f"GET_REPORT: {ev}\nRESPONSE({self.last_rep:02x}): {rep.hex()}"
                    )
                case "set_report":
                    self.dev.send_set_report_reply(ev["id"], 0)
                    logger.info(
                        f"SET_REPORT({ev['rnum']:02x}:{ev['rtype']:02x}): {trim(ev['data']).hex()}"
                    )
                    self.last_rep = ev["data"][3]
                case "output":
                    logger.info(f"OUTPUT")
                case _:
                    logger.warning(f"UKN_EVENT: {ev}")

        return out

    def consume(self, events: Sequence[Event]):
        pass
