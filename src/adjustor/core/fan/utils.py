import os

FAN_HWMONS_LEGACY = ["oxpec"]
FAN_HWMONS = ["oxp_ec", "gpdfan"]
HWMON_DIR = "/sys/class/hwmon"


def get_hwmon():
    for dir in os.listdir(HWMON_DIR):
        if dir.startswith("hwmon"):
            yield dir


def find_edge_temp():
    for hwmon in get_hwmon():
        with open(f"{HWMON_DIR}/{hwmon}/name") as f:
            name = f.read().strip()

        if name != "amdgpu":
            continue

        # For sanity, check the device has CPUs to avoid hooking an eGPU.
        if not os.path.exists(f"{HWMON_DIR}/{hwmon}/device/local_cpus"):
            continue

        if not os.path.exists(f"{HWMON_DIR}/{hwmon}/temp1_input"):
            continue

        return f"{HWMON_DIR}/{hwmon}/temp1_input"


def find_tctl_temp():
    for hwmon in get_hwmon():
        with open(f"{HWMON_DIR}/{hwmon}/name") as f:
            name = f.read().strip()

        if name != "k10temp":
            continue

        # For sanity, check the device has CPUs to avoid hooking an eGPU.
        if not os.path.exists(f"{HWMON_DIR}/{hwmon}/device/local_cpus"):
            continue

        if not os.path.exists(f"{HWMON_DIR}/{hwmon}/temp1_input"):
            continue

        return f"{HWMON_DIR}/{hwmon}/temp1_input"


def find_fans():
    """Finds tunable fans with endpoints pwmX and pwmX_enable."""
    fans = []
    for hwmon in get_hwmon():
        with open(f"{HWMON_DIR}/{hwmon}/name") as f:
            name = f.read().strip()

        if name not in FAN_HWMONS and name not in FAN_HWMONS_LEGACY:
            continue

        for fn in os.listdir(f"{HWMON_DIR}/{hwmon}"):
            if (
                fn.startswith("pwm")
                and fn[3:].isdigit()
                and os.path.exists(f"{HWMON_DIR}/{hwmon}/{fn}_enable")
            ):
                idx = fn[3:]
                speed = f"fan{idx}_input"
                if speed in os.listdir(f"{HWMON_DIR}/{hwmon}"):
                    speed_fn = f"{HWMON_DIR}/{hwmon}/{speed}"
                else:
                    speed_fn = None
                fans.append(
                    (
                        f"{HWMON_DIR}/{hwmon}/{fn}",
                        f"{HWMON_DIR}/{hwmon}/{fn}_enable",
                        speed_fn,
                        name in FAN_HWMONS_LEGACY,
                    )
                )

    return fans


def read_temp(path: str) -> float:
    with open(path, "r") as f:
        return int(f.read()) / 1000


def read_fan_speed(path: str) -> int:
    with open(path, "r") as f:
        return int(f.read())


def write_fan_speed(path: str, speed: int):
    with open(path, "w") as f:
        f.write(str(speed))
