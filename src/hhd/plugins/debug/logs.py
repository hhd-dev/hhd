from hhd.logging import RASTER
import sys
import subprocess

IMPORTANT_FILES = {
    "/sys/class/dmi/id/board_vendor": "Board Vendor",
    "/sys/class/dmi/id/board_name": "Board Name",
    "/sys/class/dmi/id/board_version": "Board Version",
    "/sys/class/dmi/id/product_family": "Product Family",
    "/sys/class/dmi/id/product_name": "Product Name",
    "/sys/class/dmi/id/sys_vendor": "System Vendor",
    "/sys/class/dmi/id/modalias": "DMI Modalias",
    "/sys/class/dmi/id/bios_version": "BIOS Version",
    "/sys/class/dmi/id/ec_firmware_release": "EC Firmware",
}

JOURNAL_FIRST_LINES = 1_000
JOURNAL_MAX_SIZE = 8_000

JOURNALCTL_CMD = lambda boot: [
    "journalctl",
    "--no-pager",
    "--no-hostname",
    "-b",
    f"{boot}",
]

JOURNALCTL_BLACKLIST = [
    "vivaldi",
]


def get_log(boot: int) -> str:
    import datetime

    out = RASTER

    out += f"""
Debug Log created by Handheld Daemon at {datetime.datetime.now().strftime('%d/%m/%Y, %H:%M:%S')}.

"""

    out += "# Device Information\n"

    for path, name in IMPORTANT_FILES.items():
        try:
            with open(path, "r") as f:
                out += f'{name} ({path}):\n"{f.read().strip()}"\n'
        except Exception as e:
            out += f"Error reading {name} ({path}): {e}\n"

    out += "Kernel Version (uname -sr):\n"
    try:
        out += f"\"{subprocess.run(
            ['uname', '-sr'], capture_output=True, text=True
        ).stdout.strip()}\"\n"
    except Exception as e:
        out += f"Error reading kernel version: {e}\n"

    out += "\n# OS Release\n"
    try:
        with open("/etc/os-release", "r") as f:
            out += f"{f.read()}"
    except Exception as e:
        out += f"Error reading /etc/os-release: {e}\n"

    out += f"\n\n# Journalctl from boot index {boot}\n"
    try:
        lines = list(
            subprocess.run(
                JOURNALCTL_CMD(boot), capture_output=True, text=True
            ).stdout.splitlines()
        )

        # Write last lines last to allow truncating the middle
        written = []
        for line in reversed(
            lines[max(JOURNAL_FIRST_LINES, len(lines) - JOURNAL_MAX_SIZE) :]
        ):
            if not any(bl in line for bl in JOURNALCTL_BLACKLIST):
                written.append(line)
                if len(written) >= JOURNAL_MAX_SIZE:
                    written.append("\n... (truncated)\n")
                    break

        # Write first lines
        for line in reversed(lines[:JOURNAL_FIRST_LINES]):
            if not any(bl in line for bl in JOURNALCTL_BLACKLIST):
                written.append(line)

        out += "\n".join(reversed(written))

    except Exception as e:
        out += f"Error reading journalctl: {e}\n"

    return out


if __name__ == "__main__":
    print(get_log(0))
