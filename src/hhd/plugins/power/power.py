import logging
import os
import subprocess

from hhd.i18n import _

# TODO: Flip this to 0 on release
HHD_SWAP_CREATE = os.environ.get("HHD_SWAP_CREATE", "0") == "1"
HHD_SWAP_SUBVOL = os.environ.get("HHD_SWAP_SUBVOL", "/var/swap")
HHD_SWAP_FILE = os.environ.get("HHD_SWAP_FILE", "/var/swap/hhdswap")

SAFETY_BUFFER = 1.3
ZRAM_MULTIPLIER = 1.5

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


def is_btrfs(fn):
    print()
    return (
        subprocess.run(
            ["stat", "-f", "-c", "%T", fn],
            check=True,
            stdout=subprocess.PIPE,
            text=True,
        ).stdout.strip()
        == "btrfs"
    )


def create_subvol():
    # First, create subvol dir to make checks
    os.makedirs(HHD_SWAP_SUBVOL, exist_ok=True)

    # Check filesystem is btrfs
    if not is_btrfs(HHD_SWAP_SUBVOL):
        logger.info("Swap filesystem is not btrfs. Skipping subvolume creation.")
        return

    # Check if subvolume already exists
    if (
        subprocess.run(
            ["btrfs", "subvolume", "show", HHD_SWAP_SUBVOL],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode
        == 0
    ):
        logger.info(
            f"Swap subvolume {HHD_SWAP_SUBVOL} already exists. Skipping creation."
        )
        return

    # Fixup selinux for swap
    subprocess.run(
        ["semanage", "fcontext", "-a", "-t", "var_t", HHD_SWAP_SUBVOL],
    )
    subprocess.run(["restorecon", HHD_SWAP_SUBVOL])

    logger.info(f"Creating swap subvolume {HHD_SWAP_SUBVOL}")
    os.system(f"btrfs subvolume create {HHD_SWAP_SUBVOL}")


def get_meminfo():
    with open("/proc/meminfo") as f:
        lines = f.readlines()

    meminfo = {}
    for line in lines:
        key, value = line.split(":")
        meminfo[key.strip()] = int(value.strip().split(" ")[0])

    return meminfo


def create_temporary_swap():
    if not HHD_SWAP_CREATE:
        return

    swapdata = subprocess.run(
        ["swapon", "--show", "--raw"], capture_output=True, text=True
    ).stdout.split("\n")[1:]

    # Check if there is a swap on disk
    has_swap = any(["/dev/zram" not in line and line for line in swapdata])
    assert not has_swap, (
        "Found swap partition. We cannot create temporary swap. Bail second attempt. Swap output:\n"
        + "\n".join(swapdata)
    )

    if HHD_SWAP_SUBVOL:
        create_subvol()

    # Check if there is a ZRAM swap partition
    has_zram = any(["/dev/zram" in line for line in swapdata])
    meminfo = get_meminfo()

    required_kb = meminfo["MemTotal"] - meminfo["MemFree"]
    required_kb *= SAFETY_BUFFER
    # ZRAM can compress a lot, add a safety buffer
    if has_zram:
        required_kb *= ZRAM_MULTIPLIER

    if os.path.exists(HHD_SWAP_FILE):
        os.remove(HHD_SWAP_FILE)

    if is_btrfs(os.path.dirname(HHD_SWAP_FILE)):
        logger.info(f"Creating BTRFS swapfile {HHD_SWAP_FILE}")
        subprocess.run(
            [
                "btrfs",
                "filesystem",
                "mkswapfile",
                HHD_SWAP_FILE,
                "--size",
                f"{int(required_kb)}k",
            ],
            check=True,
        )
    else:
        logger.info(f"Creating swapfile {HHD_SWAP_FILE} (w fallocate/mkswap)")
        subprocess.run(
            ["fallocate", "-l", f"{int(required_kb)}K", HHD_SWAP_FILE], check=True
        )
        subprocess.run(["chmod", "600", HHD_SWAP_FILE], check=True)
        subprocess.run(["mkswap", HHD_SWAP_FILE], check=True)

    # Fixup selinux for swap
    subprocess.run(
        [
            "semanage",
            "fcontext",
            "-a",
            "-t",
            "swapfile_t",
            HHD_SWAP_FILE,
        ],
    )
    subprocess.run(["restorecon", HHD_SWAP_FILE])

    # Enable swap
    subprocess.run(["swapon", HHD_SWAP_FILE], check=True)

    # Reset resume device so systemd does not get confused
    with open("/sys/power/resume", "w") as f:
        f.write("0:0")
    with open("/sys/power/resume_offset", "w") as f:
        f.write("0")

    # Disable zram to avoid confusing the kernel
    # Systemd will re-enable it after hibernation
    for zram in swapdata:
        if "/dev/zram" not in zram:
            continue

        zram = zram.strip().split(" ")[0]
        logger.info(f"Disabling ZRAM swap {zram}")
        subprocess.run(["swapoff", zram], check=True)


def delete_temporary_swap():
    if not HHD_SWAP_CREATE:
        return

    if not os.path.exists(HHD_SWAP_FILE):
        return

    logger.info(f"Deleting swapfile {HHD_SWAP_FILE}")
    try:
        subprocess.run(
            ["swapoff", HHD_SWAP_FILE], check=True, stdout=subprocess.DEVNULL
        )
    except Exception as e:
        logger.error(f"Failed to swapoff {HHD_SWAP_FILE}:\n{e}")
    try:
        os.remove(HHD_SWAP_FILE)
    except Exception as e:
        logger.error(f"Failed to delete {HHD_SWAP_FILE}:\n{e}")


def emergency_shutdown():
    logger.error("HIBERNATION FAILED. INITIATING EMERGENCY SHUTDOWN.")
    os.system("systemctl poweroff")


def supports_sleep():
    # https://gitlab.freedesktop.org/drm/amd/-/blob/master/scripts/amd_s2idle.py
    try:
        fn = os.path.join("/", "sys", "power", "mem_sleep")
        if not os.path.exists(fn):
            logger.error(
                "Kernel compiled without sleep support. Sleep button will force hibernate."
            )
            return False

        with open(fn) as f:
            sleep = f.read().strip()

        if "deep" in sleep:
            logger.info("S3 sleep supported, sleep button will work.")
            return True

        import struct

        target = os.path.join("/", "sys", "firmware", "acpi", "tables", "FACP")
        with open(target, "rb") as r:
            r.seek(0x70)
            BIT = lambda x: 1 << x
            found = struct.unpack("<I", r.read(4))[0] & BIT(21)
            s2idle_supported = bool(found)

        if s2idle_supported:
            logger.info("S2idle sleep supported, sleep button will work.")
        else:
            logger.error(
                "S2idle sleep not supported. Sleep button will force hibernate."
            )

        return s2idle_supported

    except Exception as e:
        logging.error(f"Failed to read FADT: {e}. Assuming sleep is supported")
    return True


def emergency_hibernate(shutdown: bool = False):
    # Try to hibernate with built in swap
    logger.warning("Commencing emergency hibernation")

    logger.info("Dropping caches")
    with open("/proc/sys/vm/drop_caches", "w") as f:
        f.write("3")

    logger.info("Hibernating")
    # Here loginctl does a soft swap check and errors
    # out if there is no swap
    ret = os.system("systemctl hibernate")
    if not ret:
        return ""

    status = _("Failed to hibernate (missing swap file).")

    if HHD_SWAP_CREATE:
        # Create temporary swap and hibernate
        logger.warning(
            "Hibernation failed (presumably no swap), creating temporary swap and hibernating"
        )
        try:
            create_temporary_swap()
            created = True
        except Exception as e:
            logger.error(f"Failed to create temporary swap:\n{e}")
            created = False
            status = _("Failed to create temporary swap.")

        if created:
            ret = os.system("systemctl hibernate")

            # If this fails we have to emergency shutdown
            # FIXME: That function returns before hibernation is complete
            if not ret:
                return ""

            status = _("Failed to hibernate to temporary swap.")

    if shutdown:
        emergency_shutdown()
    return status


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    HHD_SWAP_CREATE = True
    emergency_hibernate(shutdown=False)
