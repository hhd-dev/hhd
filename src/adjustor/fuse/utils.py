import os
import logging
import sys

logger = logging.getLogger(__name__)

TDP_MOUNT = "/run/hhd-tdp/card"
FUSE_MOUNT_SOCKET = "/run/hhd-tdp/socket"


def find_igpu():
    for hw in os.listdir("/sys/class/hwmon"):
        if not hw.startswith("hwmon"):
            continue
        if not os.path.exists(f"/sys/class/hwmon/{hw}/name"):
            continue
        with open(f"/sys/class/hwmon/{hw}/name") as f:
            if "amdgpu" not in f.read():
                continue

        logger.info(f'Found AMD GPU at "/sys/class/hwmon/{hw}"')

        if not os.path.exists(f"/sys/class/hwmon/{hw}/device"):
            logger.error(f'No device symlink found for "{hw}"')
            continue

        if not os.path.exists(f"/sys/class/hwmon/{hw}/device/local_cpulist"):
            logger.warning(
                f'No local_cpulist found for "{hw}". Assuming it is a dedicated unit.'
            )
            continue

        pth = os.path.realpath(os.path.join("/sys/class/hwmon", hw, "device"))
        logger.info(f'Found iGPU at "{pth}"')
        return pth

    logger.error("No iGPU found. Binding TDP attributes will not be possible.")
    return None


def prepare_tdp_mount(debug: bool = False):
    try:
        gpu = find_igpu()
        if not gpu:
            return False

        if os.path.ismount(gpu):
            logger.info(f"GPU FUSE mount is already mounted at:\n'{gpu}'")
            return True

        if not os.path.exists(TDP_MOUNT):
            os.makedirs(TDP_MOUNT)

        if not os.path.ismount(TDP_MOUNT):
            logger.info(f"Creating bind mount for:\n'{gpu}'\nto:\n'{TDP_MOUNT}'")
            os.system(f"mount --bind '{gpu}' '{TDP_MOUNT}'")
            logger.info(f"Making bind mount private.")
            os.system(f"mount --make-private '{TDP_MOUNT}'")
        else:
            logger.info(f"Bind mount already exists at:\n'{TDP_MOUNT}'")

        logger.info(f"Launching FUSE mount over:\n'{gpu}'")
        exe_python = sys.executable
        cmd = (
            f"{exe_python} -m adjustor.fuse.driver '{gpu}'"
            + f" -o root={TDP_MOUNT} -o nonempty -o allow_other"
        )
        if debug:
            cmd += " -f"
        os.system(cmd)
    except Exception as e:
        logger.error(f"Error preparing fuse mount:\n{e}")
        return False

    return True


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    prepare_tdp_mount(True)
