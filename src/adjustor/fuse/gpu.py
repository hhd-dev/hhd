import logging
import os
from typing import Literal, NamedTuple
from typing import Sequence

from adjustor.fuse.utils import find_igpu

logger = logging.getLogger(__name__)
GPU_FREQUENCY_PATH = "device/pp_od_clk_voltage"
GPU_LEVEL_PATH = "device/power_dpm_force_performance_level"
CPU_BOOST_PATH = "/sys/devices/system/cpu/amd_pstate/cpb_boost"

CPU_PATH = "/sys/devices/system/cpu/"
CPU_PREFIX = "cpu"
BOOST_FN = "cpufreq/boost"
EPP_AVAILABLE_FN = "cpufreq/energy_performance_available_preferences"
EPP_FN = "cpufreq/energy_performance_preference"
GOVERNOR_FN = "cpufreq/scaling_governor"

CPU_FREQ_DRIVER_MIN_FN = "cpufreq/cpuinfo_min_freq"
CPU_FREQ_DRIVER_MAX_FN = "cpufreq/cpuinfo_max_freq"
CPU_FREQ_NONLINEAR_MIN_FN = "cpufreq/amd_pstate_lowest_nonlinear_freq"
CPU_FREQ_MAX_FN = "cpufreq/scaling_max_freq"
CPU_FREQ_MIN_FN = "cpufreq/scaling_min_freq"

EPP_MODES = ("performance", "balance_performance", "balance_power", "power")
EppStatus = Literal["performance", "balance_performance", "balance_power", "power"]


class GPUStatus(NamedTuple):
    mode: Literal["auto", "manual", "unknown"]
    freq: int
    freq_min: int
    freq_max: int
    cpu_boost: bool | None
    epp_avail: Sequence[EppStatus] | None
    epp: EppStatus | None


def get_igpu_status():
    hwmon = find_igpu()
    if not hwmon:
        return None

    freq_min = None
    freq_max = None
    freq = None

    epp_avail = None
    epp = None

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

    cpu_boost_fn = os.path.join(CPU_PATH, CPU_PREFIX + "0", BOOST_FN)
    if os.path.exists(cpu_boost_fn):
        with open(cpu_boost_fn, "r") as f:
            cpu_boost = f.read().strip() == "1"
    elif os.path.exists(CPU_BOOST_PATH):
        with open(CPU_BOOST_PATH, "r") as f:
            cpu_boost = f.read().strip() == "1"
    else:
        cpu_boost = None

    epp_avail_fn = os.path.join(CPU_PATH, CPU_PREFIX + "0", EPP_AVAILABLE_FN)
    if os.path.exists(epp_avail_fn):
        with open(epp_avail_fn, "r") as f:
            epp_avail: Sequence[EppStatus] | None = [
                p for p in f.read().strip().split() if p in EPP_MODES
            ]

    epp_fn = os.path.join(CPU_PATH, CPU_PREFIX + "0", EPP_FN)
    if os.path.exists(epp_fn):
        with open(epp_fn, "r") as f:
            tmp = f.read().strip().split()
            if tmp in EPP_MODES:
                epp = tmp

    if freq and freq_min and freq_max and mode:
        return GPUStatus(
            mode=mode,
            freq=freq,
            freq_min=freq_min,
            freq_max=freq_max,
            cpu_boost=cpu_boost,
            epp_avail=epp_avail,
            epp=epp,
        )
    return None


def set_gpu_auto():
    logger.info("Setting GPU mode to 'auto'.")
    hwmon = find_igpu()
    if not hwmon:
        return None
    with open(os.path.join(hwmon, GPU_LEVEL_PATH), "w") as f:
        f.write("auto")


def set_gpu_manual(min_freq: int, max_freq: int | None = None):
    if max_freq is None:
        max_freq = min_freq

    logger.info(f"Pinning GPU frequency to '{min_freq}Mhz' - '{max_freq}Mhz'.")
    hwmon = find_igpu()
    if not hwmon:
        return None
    with open(os.path.join(hwmon, GPU_LEVEL_PATH), "w") as f:
        f.write("manual")

    for cmd in [f"s 0 {min_freq}\n", f"s 1 {max_freq}\n", f"c\n"]:
        with open(os.path.join(hwmon, GPU_FREQUENCY_PATH), "w") as f:
            f.write(cmd)


def read_from_cpu0(fn: str):
    with open(os.path.join(CPU_PATH, CPU_PREFIX + "0", fn), "r") as f:
        return f.read().strip()


def is_in_cpu0(fn: str):
    return os.path.exists(os.path.join(CPU_PATH, CPU_PREFIX + "0", fn))


def set_per_cpu(fn: str, value: str):
    for dir in os.listdir(CPU_PATH):
        if not dir.startswith(CPU_PREFIX):
            continue
        # Make sure CPU# is a number
        try:
            int(dir[len(CPU_PREFIX) :])
        except ValueError:
            continue
        with open(os.path.join(CPU_PATH, dir, fn), "w") as f:
            f.write(value)


def set_cpu_boost(enable: bool):
    logger.info(f"{'Enabling' if enable else 'Disabling'} CPU boost.")
    if os.path.exists(CPU_BOOST_PATH):
        try:
            with open(CPU_BOOST_PATH, "w") as f:
                f.write("1" if enable else "0")
        except Exception:
            with open(CPU_BOOST_PATH, "w") as f:
                f.write("enabled" if enable else "disabled")
    elif is_in_cpu0(BOOST_FN):
        set_per_cpu(BOOST_FN, "1" if enable else "0")


def set_epp_mode(mode: EppStatus):
    logger.info(f"Setting EPP mode to '{mode}'.")
    set_per_cpu(EPP_FN, mode)


def set_powersave_governor():
    logger.info("Setting CPU governor to 'powersave'.")
    set_per_cpu(GOVERNOR_FN, "powersave")


def can_use_nonlinear():
    return is_in_cpu0(CPU_FREQ_NONLINEAR_MIN_FN)


def set_frequency_scaling(nonlinear: bool):
    if nonlinear:
        min_freq = read_from_cpu0(CPU_FREQ_NONLINEAR_MIN_FN)
    else:
        min_freq = read_from_cpu0(CPU_FREQ_DRIVER_MIN_FN)
    max_freq = read_from_cpu0(CPU_FREQ_DRIVER_MAX_FN)

    try:
        logger.info(
            f"Setting CPU frequency scaling to [{int(min_freq)/1e6:.3f} GHz, {int(max_freq)/1e6:.3f} GHz]{' (nonlinear)' if nonlinear else ''}."
        )
    except Exception:
        pass
    set_per_cpu(CPU_FREQ_MIN_FN, min_freq)
    set_per_cpu(CPU_FREQ_MAX_FN, max_freq)
