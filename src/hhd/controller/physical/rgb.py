import os
import time
from typing import TYPE_CHECKING, Any, Sequence

if TYPE_CHECKING:
    from hhd.controller.base import RgbLedEvent, Event

from hhd.controller import Consumer


def write_sysfs(dir: str, fn: str, val: Any):
    with open(os.path.join(dir, fn), "w") as f:
        f.write(str(val))


def read_sysfs(dir: str, fn: str, default: str | None = None):
    try:
        with open(os.path.join(dir, fn), "r") as f:
            return f.read().strip()
    except Exception as e:
        if default is not None:
            return default
        raise e


def chassis_led_sysfs_path():
    old_path = "/sys/class/leds/multicolor:chassis/device"
    new_path = "/sys/class/leds/multicolor:chassis/"

    if os.path.exists(old_path):
        return old_path

    if os.path.exists(new_path):
        return new_path

    return None


def is_led_supported():
    return chassis_led_sysfs_path() is not None


def chassis_led_set(path: str, ev: RgbLedEvent):
    if ev["type"] != "led":
        return

    match ev["mode"]:
        case "solid":
            r_mode = 1
        case _:
            r_mode = 0

    r_brightness = min(max(int(ev["brightness"] * 255), 255), 0)
    r_red = min(max(ev["red"], 255), 0)
    r_green = min(max(ev["green"], 255), 0)
    r_blue = min(max(ev["blue"], 255), 0)

    write_sysfs(path, "led_mode", r_mode)
    write_sysfs(path, "brightness", r_brightness)
    write_sysfs(path, "multi_intensity", f"{r_red} {r_green} {r_blue}")


class LedDevice(Consumer):
    def __init__(self, rate_limit: float = 4) -> None:
        self.path = chassis_led_sysfs_path()
        self.supported = self.path is not None
        self.min_delay = 1 / rate_limit
        self.queued = None
        self.last = time.time() - self.min_delay

    def consume(self, events: Sequence[Event]):
        if not self.path:
            return

        curr = time.time()
        ev = None

        # Pop queued event if possible
        if self.queued:
            e, t = self.queued
            if curr > t:
                e = ev
            self.queued = None

        # Find newer event if it exists
        for e in events:
            if e["type"] == "led":
                ev = e
                # Clear queue since there
                # is a newer event
                self.queued = None

        # If no led event return
        if ev is None:
            return

        if curr > self.last + self.min_delay:
            chassis_led_set(self.path, ev)
            self.last = curr
        else:
            self.queued = (ev, curr + self.min_delay)
