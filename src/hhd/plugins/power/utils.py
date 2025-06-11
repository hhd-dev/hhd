import logging
import os
import time

WAKEUP_DIR = "/sys/class/wakeup"
SMBIOS_FN = "/sys/firmware/dmi/entries/1-0/raw"

def main_loop():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    logger = logging.getLogger(__name__)

    event_counts = {}
    wakeup_counts = {}
    old_reason = None

    while True:
        for entry in os.scandir(WAKEUP_DIR):
            if not entry.is_dir():
                continue

            with open(os.path.join(entry.path, "event_count"), "r") as f:
                event_count = f.read().strip()

            with open(os.path.join(entry.path, "wakeup_count"), "r") as f:
                wakeup_count = f.read().strip()

            diff = False
            if entry.path not in wakeup_counts:
                wakeup_counts[entry.path] = wakeup_count
                # diff = True

            if wakeup_counts[entry.path] != wakeup_count:
                diff = True
                wakeup_counts[entry.path] = wakeup_count
            
            if entry.path not in event_counts:
                event_counts[entry.path] = event_count
                # diff = True
            
            if event_counts[entry.path] != event_count:
                diff = True
                event_counts[entry.path] = event_count
            
            if not diff:
                continue

            with open(os.path.join(entry.path, "name"), "r") as f:
                name = f.read().strip()

            logger.info(f"{name:>20s}: {wakeup_count:>3s} wakeups, {event_count:>3s} events")
            wakeup_counts[entry.path] = wakeup_count

        with open(SMBIOS_FN, "rb") as f:
            smbios = f.read()

        wakeup_reason = smbios[24]
        # 00h Reserved
        # 01h Other
        # 02h Unknown
        # 03h APM Timer
        # 04h Modem Ring
        # 05h LAN Remote
        # 06h Power Switch
        # 07h PCI PME#
        # 08h AC Power Restored
        match wakeup_reason:
            case 0x00:
                reason = "Reserved"
            case 0x01:
                reason = "Other"
            case 0x02:
                reason = "Unknown"
            case 0x03:
                reason = "APM Timer"
            case 0x04:
                reason = "Modem Ring"
            case 0x05:
                reason = "LAN Remote"
            case 0x06:
                reason = "Power Switch"
            case 0x07:
                reason = "PCI PME#"
            case 0x08:
                reason = "AC Power Restored"
            case _:
                reason = f"Unknown ({wakeup_reason:02X})"

        if old_reason != reason:
            logger.info(f"Wakeup reason: {reason}")
            old_reason = reason

        time.sleep(0.2)


def main():
    try:
        main_loop()
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()
