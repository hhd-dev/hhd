import logging
import subprocess
from typing import NamedTuple, Sequence

logger = logging.getLogger(__name__)


class Command(NamedTuple):
    method: str
    args: Sequence[bytes]


def initialize():
    try:
        subprocess.run(["modprobe", "acpi_call"], capture_output=True)
        return True
    except Exception as e:
        logger.error(f"Failed initializing acpi_call with error:\n{e}")
        return False


def call(method: str, args: Sequence[bytes | int]):
    cmd = method
    for arg in args:
        if isinstance(arg, int):
            cmd += f" 0x{arg:02x}"
        else:
            cmd += f" b{arg.hex()}"
    logger.info(f"Executing '{cmd}'")

    try:
        with open("/proc/acpi/call", "wb") as f:
            f.write(cmd.encode())
        return True
    except Exception as e:
        logger.error(f"ACPI Call failed with error:\n{e}")
        return False


def read():
    with open("/proc/acpi/call", "rb") as f:
        return f.read().decode()
