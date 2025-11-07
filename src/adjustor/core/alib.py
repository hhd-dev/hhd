from .acpi import call
import logging
from typing import NamedTuple, Literal


class AlibParams(NamedTuple):
    id: int
    min: int
    max: int
    scale: int = 1


class DeviceParams(NamedTuple):
    min: int | None
    smin: int | None
    default: int | None
    smax: int | None
    max: int | None


Limit = Literal["device", "expanded", "cpu", "unlocked"]
A = AlibParams
D = DeviceParams

logger = logging.getLogger(__name__)


def alib(
    params: dict[str, int],
    cpu: dict[str, A],
    limit: Limit = "device",
    dev: dict[str, D] = {},
):
    length = 2
    data = bytearray()
    info = f"Sending SMU command with {len(params)} parameters:"
    for name, val in params.items():
        length += 5
        if name not in cpu:
            logger.error(
                f"Command '{name}' not found in instructions:\n{cpu}\nSkipping ALIB command."
            )
            return False

        cmd, cmin, cmax, scale = cpu[name]
        if limit != "unlocked" and (val < cmin or val > cmax):
            logger.error(f"Value {val} violates APU limit for {name}: {cpu[name]}")
            return False

        if dev and name in dev:
            dmin, smin, _, smax, dmax = dev[name]
            if limit == "device" and (
                (dmin is not None and val < dmin) or (dmax is not None and val > dmax)
            ):
                logger.error(
                    f"Value {val} violates device limit for {name}: {dev[name]}"
                )
                return False
            if limit in ("device", "expanded") and (
                (smin is not None and val < smin) or (smax is not None and val > smax)
            ):
                logger.error(
                    f"Value {val} violates expanded device limit for {name}: {dev[name]}"
                )
                return False

        data.append(cmd)
        data.extend(
            int.to_bytes(scale * val, length=4, byteorder="little", signed=False)
        )
        info += f"\n - {name:>12s} (0x{cmd:02x}): {val}"

    b_length = int.to_bytes(length, length=2, byteorder="little", signed=False)
    logger.info(info)
    return call(r"\_SB.ALIB", [0x0C, b_length + data])
