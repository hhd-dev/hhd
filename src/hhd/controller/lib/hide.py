import subprocess
import os


def get_syspath(devpath: str):
    for line in subprocess.run(
        ["udevadm", "info", devpath], capture_output=True
    ).stdout.splitlines():
        if line.startswith(b"P: "):
            return line[3:].decode()
    return None


def get_gamepad_name(devpath: str):
    syspath = get_syspath(devpath)
    if not syspath:
        return None

    parts = syspath.split("/")
    if len(parts) < 3:
        return None
    input_dev = parts[-2]
    if not input_dev.startswith("input") or input_dev == "input":
        return None
    return input_dev


def get_parent_sysfs(devpath: str):
    syspath = get_syspath(devpath)
    if not syspath:
        return None

    return syspath[: syspath.rindex("/")]


def reload_children(parent: str):
    stat = subprocess.run(
        ["udevadm", "control", "--reload-rules"],
        capture_output=True,
    )
    if stat.returncode:
        return False
    for action in ["remove", "add"]:
        stat = subprocess.run(
            ["udevadm", "trigger", "--action", action, "-b", parent],
            capture_output=True,
        )
        if stat.returncode:
            return False
    return True


def hide_gamepad(devpath: str, vid: int, pid: int) -> str | None:
    input_dev = get_gamepad_name(devpath)
    parent = get_parent_sysfs(devpath)
    if not input_dev or not parent:
        return None

    out_fn = f"/run/udev/rules.d/95-hhd-devhide-{input_dev}.rules"
    if os.path.exists(out_fn):
        # Skip hiding controller on reloads
        return input_dev

    rule = f"""\
# Hides device gamepad devices stemming from {input_dev}
# Managed by HHD, this file will be autoremoved during configuration changes.
SUBSYSTEMS=="input", KERNELS=="{input_dev}", ATTRS{{id/vendor}}=="{vid:04x}", ATTRS{{id/product}}=="{pid:04x}", GOTO="hhd_valid"
GOTO="hhd_end"
LABEL="hhd_valid"
KERNEL=="js[0-9]*|event[0-9]*", SUBSYSTEM=="input", MODE="000", GROUP="root", TAG-="uaccess", RUN+="/bin/chmod 000 /dev/input/%k"
LABEL="hhd_end"
"""  # , RUN+="/bin/chmod 000 /sys/%p"
    try:
        os.makedirs("/run/udev/rules.d/", exist_ok=True)
        with open(out_fn, "w") as f:
            f.write(rule)
        reload_children(parent)
        return input_dev
    except Exception:
        return None


def unhide_gamepad(devpath: str, root: str | None = None):
    try:
        # Remove file before searching for device
        if root is not None:
            os.remove(f"/run/udev/rules.d/95-hhd-devhide-{root}.rules")
    except Exception:
        return False

    input_dev = get_gamepad_name(devpath)
    parent = get_parent_sysfs(devpath)
    if not input_dev or not parent:
        return False

    try:
        if root is None:
            os.remove(f"/run/udev/rules.d/95-hhd-devhide-{input_dev}.rules")
        return reload_children(parent)
    except Exception:
        return False


def unhide_all():
    try:
        for rule in os.listdir("/run/udev/rules.d/"):
            if rule.startswith("95-hhd-devhide"):
                os.remove(os.path.join("/run/udev/rules.d/", rule))
    except Exception:
        pass
