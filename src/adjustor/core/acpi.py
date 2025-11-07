import logging
import os
import subprocess
from typing import NamedTuple, Sequence

logger = logging.getLogger(__name__)


class Command(NamedTuple):
    method: str
    args: Sequence[bytes]


def initialize():
    try:
        o = subprocess.run(["modprobe", "acpi_call"], capture_output=True)
        logger.info(f"'acpi_call' modprobe output:\n{(o.stdout + o.stderr).decode()}".strip())
        return True
    except Exception as e:
        logger.warning(f"Failed loading acpi_call with error:\n{e}")
        return False


def check_perms():
    try:
        with open("/proc/acpi/call", "wb") as f:
            return f.writable()
    except Exception as e:
        logger.error(f"Could open acpi_call file ('/proc/acpi/call'). Error:\n{e}")
        return False


def call(method: str, args: Sequence[bytes | int], risky: bool = True):
    cmd = method
    for arg in args:
        if isinstance(arg, int):
            cmd += f" 0x{arg:02x}"
        else:
            cmd += f" b{arg.hex()}"

    log = logger.info if risky else logger.debug
    log(f"Executing ACPI call:\n'{cmd}'")

    try:
        with open("/proc/acpi/call", "wb") as f:
            f.write(cmd.encode())
        return True
    except Exception as e:
        logger.error(f"ACPI Call failed with error:\n{e}")
        return False


def read():
    with open("/proc/acpi/call", "rb") as f:
        d = f.read().decode().strip()

    if d == "not called\0":
        return None
    if d.startswith("0x") and d.endswith("\0"):
        return int(d[:-1], 16)
    if d.startswith("{") and d.endswith("}\0"):
        bs = d[1:-2].split(", ")
        return bytes(int(b, 16) for b in bs)
    assert False, f"Return value '{d}' supported yet or was truncated."
