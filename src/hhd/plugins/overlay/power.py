import logging
import subprocess

logger = logging.getLogger(__name__)


def get_windows_bootnum() -> int | None:
    try:
        s = subprocess.check_output("efibootmgr").decode("utf-8")

        for line in s.split("\n"):
            if "Windows Boot Manager" in line:
                return int(line[: line.index(" ")].replace("*", "").replace("Boot", ""))

        return None
    except Exception as e:
        return None


def boot_windows():
    bootnum = get_windows_bootnum()

    if bootnum is None:
        logger.error("Could not find Windows Boot Manager in efibootmgr output")
        return

    try:
        subprocess.run(["efibootmgr", "-n", str(bootnum)])
        logger.info(f"Booting Windows with bootnum {bootnum}")
        subprocess.run(["systemctl", "reboot"])
    except Exception as e:
        logger.error(f"Failed to boot Windows: {e}")
