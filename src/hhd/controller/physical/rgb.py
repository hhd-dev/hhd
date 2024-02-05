import logging
import os
import time
from typing import Any, Sequence

from hhd.controller import Consumer
from hhd.controller.base import Event, RgbLedEvent

LED_PATH = "/sys/class/leds/multicolor:chassis/"

logger = logging.getLogger(__name__)


def write_sysfs(dir: str, fn: str, val: Any):
    logger.info(f"Writing `{str(val)}` to \n{os.path.join(dir, fn)}")
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


def is_led_supported():
    return os.path.exists(LED_PATH)


def chassis_led_set(ev: RgbLedEvent):
    if ev["type"] != "led":
        return

    match ev["mode"]:
        case "solid":
            r_mode = 1
        case _:
            r_mode = 0

    r_brightness = max(min(int(ev["brightness"] * 255), 255), 0)
    r_red = max(min(ev["red"], 255), 0)
    r_green = max(min(ev["green"], 255), 0)
    r_blue = max(min(ev["blue"], 255), 0)

    # Mode only exists on ayn devices
    try:
        write_sysfs(LED_PATH, "led_mode", r_mode)
    except Exception:
        logger.info("Could not write led_mode (not applicable for Ayaneo, only Ayn).")
        try:
            write_sysfs(LED_PATH, "device/led_mode", r_mode)
        except Exception:
            logger.info("Could not write led_mode to secondary path.")

    write_sysfs(LED_PATH, "brightness", r_brightness)
    write_sysfs(LED_PATH, "multi_intensity", f"{r_red} {r_green} {r_blue}")


class LedDevice(Consumer):
    def __init__(self, rate_limit: float = 4) -> None:
        self.supported = is_led_supported()
        self.min_delay = 1 / rate_limit
        self.queued = None
        self.last = time.time() - self.min_delay

    def consume(self, events: Sequence[Event]):
        if not self.supported:
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
            try:
                chassis_led_set(ev)
            except Exception as e:
                logger.error(f"Setting leds failed with error:\n{e}")
                # Turn off support
                self.supported = False
            self.last = curr
        else:
            self.queued = (ev, curr + self.min_delay)
