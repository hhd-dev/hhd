import subprocess
import os
import logging
import re
import threading

from .ioctl import EVIOCREVOKEALL, JSIOCREVOKEALL
from fcntl import ioctl

logger = logging.getLogger(__name__)

ENHANCED_HIDING = os.environ.get("HHD_EVIOC_IOCTL", "0") == "1"
HIDE_ALL = os.environ.get("HHD_HIDE_ALL", "0") == "1"

_hidden = []

def get_device_info(devpath: str):
    syspath = None
    for line in subprocess.run(
        ["udevadm", "info", devpath], capture_output=True
    ).stdout.splitlines():
        if line.startswith(b"P: "):
            return line[3:].decode()

    return syspath


def get_gamepad_name(syspath: str):
    parts = syspath.split("/")
    if len(parts) < 3:
        return None
    input_dev = parts[-2]
    if not input_dev.startswith("input") or input_dev == "input":
        return None
    return input_dev


def get_parent_sysfs(syspath: str):
    return syspath[: syspath.rindex("/")]
    # return syspath.split("/input/")[0]


def get_usb_device(syspath: str) -> tuple[str | None, str | None]:
    parts = syspath.split("/")
    for i in range(len(parts) - 1, -1, -1):
        part = parts[i]
        if re.fullmatch(r"\d+-\d+(?:\.\d+)*", part):
            return part, "/".join(parts[: i + 1])
    return None, None


def get_hide_rule(
    input_dev: str,
    usb_root: str | None,
    vid: int,
    pid: int,
    hide_all: bool,
) -> str:
    if hide_all:
        input_match = 'ENV{ID_BUS}=="usb", '
        usb_match = (
            'SUBSYSTEMS=="usb", '
            f'ATTRS{{idVendor}}=="{vid:04x}", '
            f'ATTRS{{idProduct}}=="{pid:04x}", '
        )
    else:
        input_match = f'KERNELS=="{input_dev}", '
        usb_match = (
            f'KERNELS=="{usb_root}", '
            f'ATTRS{{idVendor}}=="{vid:04x}", '
            f'ATTRS{{idProduct}}=="{pid:04x}", '
            if usb_root
            else None
        )

    rule = f"""\
# Hides device gamepad devices stemming from {input_dev}
# Managed by HHD, this file will be autoremoved during configuration changes.
SUBSYSTEMS=="input", {input_match}ATTRS{{id/vendor}}=="{vid:04x}", ATTRS{{id/product}}=="{pid:04x}", GOTO="hhd_valid"
GOTO="hhd_end"
LABEL="hhd_valid"
# Keep SDL from falling back to probing the hidden device's sysfs capabilities.
KERNEL=="js[0-9]*|event[0-9]*", SUBSYSTEM=="input", ENV{{ID_INPUT}}="0", ENV{{ID_INPUT_JOYSTICK}}="0", ENV{{ID_INPUT_ACCELEROMETER}}="0", ENV{{ID_INPUT_KEY}}="0", ENV{{ID_INPUT_KEYBOARD}}="0", ENV{{ID_INPUT_MOUSE}}="0", ENV{{ID_INPUT_TOUCHPAD}}="0", ENV{{ID_INPUT_TOUCHSCREEN}}="0", ENV{{ID_INPUT_TABLET}}="0", ENV{{ID_INPUT_SWITCH}}="0", ENV{{ID_CLASS}}="hhd-hidden", MODE:="000", GROUP:="root", TAG-="uaccess", RUN+="/bin/chmod 000 /dev/input/%k"
LABEL="hhd_end"
"""

    if usb_match:
        rule += f"""\
# Hide raw interfaces belonging to the same physical USB controller.
SUBSYSTEM=="hidraw", {usb_match}MODE:="000", GROUP:="root", TAG-="uaccess"
SUBSYSTEM=="usb", KERNEL=="hiddev[0-9]*", {usb_match}MODE:="000", GROUP:="root", TAG-="uaccess"
"""

    return rule


_reload_thread = None


def _reload_children_worker(parent: str):
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


def reload_children(parent: str):
    global _reload_thread

    if _reload_thread:
        _reload_thread.join()
        _reload_thread = None

    _reload_thread = threading.Thread(target=_reload_children_worker, args=(parent,))
    _reload_thread.start()


def hide_gamepad(devpath: str, vid: int, pid: int) -> str | None:
    syspath = get_device_info(devpath)
    if not syspath:
        return None
    input_dev = get_gamepad_name(syspath)
    parent = get_parent_sysfs(syspath)
    usb_root, usb_parent = get_usb_device(syspath)
    reload_parent = usb_parent or parent
    if not input_dev or not parent:
        return None

    if HIDE_ALL:
        # Hide all devices with the same vid pid
        root = f"{vid:04x}-{pid:04x}"
    else:
        root = input_dev

    out_fn = f"/run/udev/rules.d/95-hhd-devhide-{root}.rules"
    if os.path.exists(out_fn):
        # Skip hiding controller on reloads
        if reload_parent not in _hidden:
            _hidden.append(reload_parent)
        return input_dev

    rule = get_hide_rule(input_dev, usb_root, vid, pid, HIDE_ALL)

    try:
        # Add udev rules to strip the device perms from the system
        os.makedirs("/run/udev/rules.d/", exist_ok=True)
        with open(out_fn, "w") as f:
            f.write(rule)
        # Reload the rules for that device to make it owned by root
        reload_children(reload_parent)
        _hidden.append(reload_parent)

        # Use flag until further testing
        if not ENHANCED_HIDING:
            return input_dev

        # Now that only we can access the device, revoke open fds
        # Custom kernel feature. NOOP if it fails.
        try:
            for fn in os.listdir("/sys/" + parent):
                if fn.startswith("event"):
                    ioc = EVIOCREVOKEALL
                elif fn.startswith("js"):
                    ioc = JSIOCREVOKEALL
                else:
                    continue

                fd = None
                try:
                    dev = os.path.join("/dev/input", fn)
                    fd = os.open(dev, os.O_RDONLY)
                    ioctl(fd, ioc, 0)
                    logger.info(f"Revoked access to device '{dev}'.")
                finally:
                    if fd:
                        os.close(fd)
        except Exception as e:
            logger.exception(
                f"Failed to run EV/JSIOCREVOKEALL. Games may remember the controller. Error:\n{e}"
            )

        return input_dev
    except Exception:
        return None


def unhide_gamepad(devpath: str, root: str | None = None):
    if HIDE_ALL:
        # Do not unhide device to be ready when the next one shows up
        return False

    try:
        # Remove file before searching for device
        if root is not None:
            os.remove(f"/run/udev/rules.d/95-hhd-devhide-{root}.rules")
    except Exception:
        return False

    syspath = get_device_info(devpath)
    if not syspath:
        return False
    input_dev = get_gamepad_name(syspath)
    _, usb_parent = get_usb_device(syspath)
    parent = usb_parent or get_parent_sysfs(syspath)
    if not input_dev or not parent:
        return False

    if parent in _hidden:
        _hidden.remove(parent)

    try:
        if root is None:
            os.remove(f"/run/udev/rules.d/95-hhd-devhide-{input_dev}.rules")
        return reload_children(parent)
    except Exception:
        return False


def unhide_all():
    removed = False
    try:
        for rule in os.listdir("/run/udev/rules.d/"):
            if rule.startswith("95-hhd-devhide"):
                os.remove(os.path.join("/run/udev/rules.d/", rule))
                logger.info(f"Removed rule '{rule}'.")
                removed = True
    except Exception:
        pass

    if not removed:
        return True

    # We have to reload affected devices if we removed rules
    for parent in _hidden:
        reload_children(parent)
    _hidden.clear()
