import logging
import os
logger = logging.getLogger(__name__)

def find_igpu():
    for hw in os.listdir("/sys/class/hwmon"):
        if not hw.startswith("hwmon"):
            continue
        if not os.path.exists(f"/sys/class/hwmon/{hw}/name"):
            continue
        with open(f"/sys/class/hwmon/{hw}/name", 'r') as f:
            if "amdgpu" not in f.read():
                continue

        if not os.path.exists(f"/sys/class/hwmon/{hw}/device"):
            logger.error(f'No device symlink found for "{hw}"')
            continue

        if not os.path.exists(f"/sys/class/hwmon/{hw}/device/local_cpulist"):
            logger.warning(
                f'No local_cpulist found for "{hw}". Assuming it is a dedicated unit.'
            )
            continue

        pth = os.path.realpath(os.path.join("/sys/class/hwmon", hw))
        return pth

    logger.error("No iGPU found. Binding TDP attributes will not be possible.")
    return None
