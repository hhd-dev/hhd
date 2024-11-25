import logging
import select
from threading import Event as TEvent
from typing import Any, Sequence

from hhd.plugins import Emitter, Event
from pyroute2 import AcpiEventSocket  # type: ignore

logger = logging.getLogger(__name__)

EVENT_MATCHES: Sequence[tuple[dict[str, Any], str]] = [
    ({"device_class": b"ac_adapter", "data": 0}, "dc"),
    ({"device_class": b"ac_adapter", "data": 256}, "ac"),
    ({"device_class": b"battery"}, "battery"),
    ({"device_class": b"button/power"}, "powerbutton"),
    # Legion GO TDP event
    ({"bus_id": b"D320289E-8FEA-"}, "tdp"),
    ({"device_class": b"wmi", "bus_id": b"PNP0C14:01"}, "tdp"), # Legion go
    # GPD Force hibernate thermal event
    # , 'type': 0xf100, 'data': 0x0100 ignore these attrs for now...
    ({"device_class": b"thermal_zone", "bus_id": b"LNXTHERM:00"}, "hibernate-thermal"),
]

GUARD_DELAY = 0.5


def loop_process_events(emit: Emitter, should_exit: TEvent):
    acpi = AcpiEventSocket()
    logger.info(f"Starting ACPI Event handler.")

    while not should_exit.is_set():
        # FIXME: Uses unofficial API, find the correct way.
        r, _, _ = select.select([acpi._sock.fileno()], [], [], GUARD_DELAY)

        if r:
            for message in acpi.get():
                ev = message.get("ACPI_GENL_ATTR_EVENT", None)

                if not ev:
                    continue

                found = False
                for match, etype in EVENT_MATCHES:
                    matches = True
                    for k, v in match.items():
                        if k not in ev or ev[k] != v:
                            matches = False
                            break

                    if matches:
                        if etype not in ("battery", "powerbutton"):
                            emit({"type": "acpi", "event": etype})  # type: ignore
                        found = True
                        break

                if not found:
                    logger.info(f"ACPI event: {ev}")
