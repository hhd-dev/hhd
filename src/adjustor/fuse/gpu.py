import logging
import os
from typing import Literal, NamedTuple

from adjustor.fuse.utils import find_igpu

logger = logging.getLogger(__name__)
GPU_FREQUENCY_PATH = "device/pp_od_clk_voltage"
GPU_LEVEL_PATH = "device/power_dpm_force_performance_level"
CPU_BOOST_PATH = "/sys/devices/system/cpu/amd_pstate/cpb_boost"


class GPUStatus(NamedTuple):
    mode: Literal["auto", "manual", "unknown"]
    freq: int
    freq_min: int
    freq_max: int
    cpu_boost: bool | None


def get_igpu_status():
    hwmon = find_igpu()
    if not hwmon:
        return None

    freq_min = None
    freq_max = None
    freq = None

    with open(os.path.join(hwmon, GPU_FREQUENCY_PATH), "r") as f:
        for line in f.readlines():
            if line.startswith("0:"):
                freq = int(line.split()[1].replace("Mhz", ""))
            if line.startswith("SCLK"):
                freq_min = int(line.split()[1].replace("Mhz", ""))
                freq_max = int(line.split()[2].replace("Mhz", ""))

    with open(os.path.join(hwmon, GPU_LEVEL_PATH), "r") as f:
        m = f.read()[:-1]
        if m == "auto":
            mode = "auto"
        elif m == "manual":
            mode = "manual"
        else:
            mode = "unknown"

    if os.path.exists(CPU_BOOST_PATH):
        with open(CPU_BOOST_PATH, "r") as f:
            cpu_boost = f.read().strip() == "1"
    else:
        cpu_boost = None

    if freq and freq_min and freq_max and mode:
        return GPUStatus(
            mode=mode,
            freq=freq,
            freq_min=freq_min,
            freq_max=freq_max,
            cpu_boost=cpu_boost,
        )
    return None


def set_gpu_auto():
    logger.info("Setting GPU mode to 'auto'.")
    hwmon = find_igpu()
    if not hwmon:
        return None
    with open(os.path.join(hwmon, GPU_LEVEL_PATH), "w") as f:
        f.write("auto")


def set_gpu_manual(freq: int):
    logger.info(f"Pinning GPU frequency to '{freq}Mhz'.")
    hwmon = find_igpu()
    if not hwmon:
        return None
    with open(os.path.join(hwmon, GPU_LEVEL_PATH), "w") as f:
        f.write("manual")

    for cmd in [f"s 0 {freq}\n", f"s 1 {freq}\n", f"c\n"]:
        with open(os.path.join(hwmon, GPU_FREQUENCY_PATH), "w") as f:
            f.write(cmd)


def set_cpu_boost(enable: bool):
    logger.info(f"{'Enabling' if enable else 'Disabling'} CPU boost.")
    if not os.path.exists(CPU_BOOST_PATH):
        return None
    with open(CPU_BOOST_PATH, "w") as f:
        f.write("1" if enable else "0")
