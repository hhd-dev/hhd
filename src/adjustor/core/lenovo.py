from .acpi import call, read
from typing import Sequence, Literal

import logging

logger = logging.getLogger(__name__)

MIN_CURVE = [44, 48, 55, 60, 71, 79, 87, 87, 100, 100]

TdpMode = Literal["quiet", "balanced", "performance", "custom"]


def get_fan_curve():
    logger.info("Retrieving fan curve.")
    o = call(r"\_SB.GZFD.WMAB", [0, 0x05, bytes([0, 0, 0, 0])], risky=False)
    if not o:
        return None
    o = read()
    if not isinstance(o, bytes):
        return None

    return [o[i] for i in range(4, 44, 4)]


def set_fan_curve(arr: Sequence[int], lim: Sequence[int] | None = None):
    logger.info(f"Setting fan curve to:\n{arr}")
    if len(arr) != 10:
        logger.error(f"Invalid fan curve length: {len(arr)}. Should be 10.")
        return False
    if any(not isinstance(d, int) for d in arr):
        logger.error(f"Curve has null value, not setting.")
        return False

    if lim:
        for a, b in zip(arr, lim):
            if a < b:
                logger.error(
                    f"Not set. Fan curve does not comply with limit:\n{len(arr)}"
                )
                return False

    return call(
        r"\_SB.GZFD.WMAB",
        [
            0,
            0x06,
            bytes(
                [
                    0x00,
                    0x00,
                    0x0A,
                    0x00,
                    0x00,
                    0x00,
                    arr[0],
                    0x00,
                    arr[1],
                    0x00,
                    arr[2],
                    0x00,
                    arr[3],
                    0x00,
                    arr[4],
                    0x00,
                    arr[5],
                    0x00,
                    arr[6],
                    0x00,
                    arr[7],
                    0x00,
                    arr[8],
                    0x00,
                    arr[9],
                    0x00,
                    0x00,
                    0x0A,
                    0x00,
                    0x00,
                    0x00,
                    0x0A,
                    0x00,
                    0x14,
                    0x00,
                    0x1E,
                    0x00,
                    0x28,
                    0x00,
                    0x32,
                    0x00,
                    0x3C,
                    0x00,
                    0x46,
                    0x00,
                    0x50,
                    0x00,
                    0x5A,
                    0x00,
                    0x64,
                    0x00,
                    0x00,
                ]
            ),
        ],
    )


def set_power_light_v1(enabled: bool):
    logger.debug(f"Setting power light status.")
    return call(r"\_SB.GZFD.WMAF", [0, 0x02, bytes([0x03, int(enabled), 0x00])])


def get_power_light_v1():
    logger.debug(f"Getting power light status.")
    if not call(r"\_SB.GZFD.WMAF", [0, 0x01, 0x03], risky=False):
        return None
    o = read()
    if isinstance(o, bytes) and len(o) == 2:
        return bool(o[0])
    return None


def set_power_light(enabled: bool, suspend: bool = False):
    logger.debug(f"Setting power light status.")
    if enabled:
        if suspend:
            cb = 0x03
        else:
            cb = 0x02
    else:
        cb = 0x01
    return call(
        r"\_SB.GZFD.WMAF",
        [0, 0x02, bytes([0x024 if suspend else 0x04, 0x00, cb])],
    )


def get_power_light(suspend: bool = False):
    logger.debug(f"Getting power light status.")
    if not call(r"\_SB.GZFD.WMAF", [0, 0x01, 0x024 if suspend else 0x04], risky=False):
        return None
    o = read()
    if isinstance(o, bytes) and len(o) == 2:
        return o[1] == (0x03 if suspend else 0x02)
    return None


def get_bios_version():
    raw = None
    try:
        with open("/sys/class/dmi/id/bios_version") as f:
            raw = f.read()
        return int(raw.replace("N3CN", "").split("WW")[0].strip())
    except Exception as e:
        logger.error(f"Failed to get BIOS version from '{raw}' with error:\n{e}")
        return 1


def get_feature(id: int):
    if not call(
        r"\_SB.GZFD.WMAE",
        [0, 0x11, int.to_bytes(id, length=4, byteorder="little", signed=False)],
        risky=False,
    ):
        return None

    return read()


def set_feature(id: int, value: int):
    return call(
        r"\_SB.GZFD.WMAE",
        [
            0,
            0x12,
            int.to_bytes(id, length=4, byteorder="little", signed=False)
            + int.to_bytes(value, length=4, byteorder="little", signed=False),
        ],
    )


def set_tdp_mode(mode: TdpMode):
    logger.info(f"Setting tdp mode to '{mode}'.")
    match mode:
        case "quiet":
            b = 0x01
        case "balanced":
            b = 0x02
        case "performance":
            b = 0x03
        case "custom":
            b = 0xFF
        case _:
            logger.error(f"TDP mode '{mode}' is unknown. Not setting.")
            return False

    return call(r"\_SB.GZFD.WMAA", [0, 0x2C, b])


def get_tdp_mode() -> TdpMode | None:
    logger.debug(f"Retrieving TDP Mode.")
    if not call(r"\_SB.GZFD.WMAA", [0, 0x2D, 0], risky=False):
        logger.error(f"Failed retrieving TDP Mode.")
        return None

    match read():
        case 0x01:
            return "quiet"
        case 0x02:
            return "balanced"
        case 0x03:
            return "performance"
        case 0xFF:
            return "custom"
        case v:
            logger.error(f"TDP mode '{v}' is unknown")
            return None


def get_steady_tdp():
    logger.debug(f"Retrieving steady TDP.")
    return get_feature(0x0102FF00)


def get_fast_tdp():
    logger.debug(f"Retrieving fast TDP.")
    return get_feature(0x0103FF00)


def get_slow_tdp():
    logger.debug(f"Retrieving slow TDP.")
    return get_feature(0x0101FF00)


def get_charge_limit():
    logger.debug(f"Retrieving charge limit.")
    return get_feature(0x03010001)


def set_charge_limit(enable: bool):
    logger.info(f"Setting charge limit (80 %) to {enable}.")
    return set_feature(0x03010001, enable)


def set_steady_tdp(val: int):
    logger.info(f"Setting steady TDP to {val}.")
    return set_feature(0x0102FF00, val)


def set_fast_tdp(val: int):
    logger.info(f"Setting fast TDP to {val}.")
    return set_feature(0x0103FF00, val)


def set_slow_tdp(val: int):
    logger.info(f"Setting slow TDP to {val}.")
    return set_feature(0x0101FF00, val)


def get_full_fan_speed():
    logger.debug(f"Getting full fan speed.")
    return get_feature(0x04020000)


def set_full_fan_speed(enable: bool):
    logger.info(f"Setting full fan mode to {enable}.")
    return set_feature(0x04020000, int(enable))
