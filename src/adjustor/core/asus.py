from .acpi import call, read
from typing import Sequence, Literal

import logging

logger = logging.getLogger(__name__)

POINTS = [
    30,
    40,
    50,
    60,
    70,
    80,
    90,
    90,
]

MIN_CURVE = [
    30,
    30,
    30,
    45,
    50,
    50,
    50,
    50,
]


def write_fan_curve(arr: list[int]):
    logger.info(f"Setting fan curve to:\n{arr}")
    if len(arr) != 8:
        logger.error(f"Invalid fan curve length: {len(arr)}. Should be 10.")
        return False
    if any(not isinstance(d, int) or d > 100 for d in arr):
        logger.error(f"Curve has null value or higher than 100, not setting.")
        return False

    for c in (0x00110024, 0x00110025):
        call(
            r" \_SB_.ATKD.WMNB",
            [
                0,
                0x53564544,
                int.to_bytes(c, length=4, byteorder="little", signed=False)
                + bytes(POINTS)
                + bytes(arr),
            ],
        )
