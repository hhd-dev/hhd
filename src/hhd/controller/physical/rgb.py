import logging
import os
import time
from threading import Event as TEvent
from threading import Thread
from typing import Any, Sequence

from hhd.controller import Consumer
from hhd.controller.base import Event, RgbLedEvent

LED_BASE = "/sys/class/leds/"
LED_PATHS = [
    "multicolor:chassis",
    ":rgb:joystick_rings",
]

logger = logging.getLogger(__name__)


def write_sysfs(dir: str, fn: str, val: Any):
    logger.info(f'Writing `{str(val)}` to \n"{os.path.join(dir, fn)}"')
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


def get_led_path():
    for fn in os.listdir(LED_BASE):
        for p in LED_PATHS:
            if p in fn:
                return os.path.join(LED_BASE, fn)
    return None


def is_led_supported():
    return get_led_path() is not None


def chassis_led_set(ev: RgbLedEvent, init: bool = True):
    if ev["type"] != "led":
        return

    led_path = get_led_path()
    if not led_path:
        return

    match ev["mode"]:
        case "solid":
            r_mode = 1
        case _:
            r_mode = 0

    max_brightness = 255
    try:
        max_brightness = int(read_sysfs(led_path, "max_brightness", "255"))
    except Exception:
        pass

    r_brightness = max(min(int(ev["brightness"] * max_brightness), max_brightness), 0)
    r_red = max(min(ev["red"], 255), 0)
    r_green = max(min(ev["green"], 255), 0)
    r_blue = max(min(ev["blue"], 255), 0)

    # Mode only exists on ayn devices
    if init:
        try:
            write_sysfs(led_path, "led_mode", r_mode)
        except Exception:
            logger.info(
                "Could not write led_mode (not applicable for Ayaneo, only Ayn)."
            )
            try:
                write_sysfs(led_path, "device/led_mode", r_mode)
            except Exception:
                logger.info("Could not write led_mode to secondary path.")

        write_sysfs(led_path, "brightness", r_brightness)

    pattern = read_sysfs(led_path, "multi_index", "red green blue")
    arr = []
    for color in pattern.split(" "):
        if color == "red":
            arr.append(r_red)
        elif color == "green":
            arr.append(r_green)
        elif color == "blue":
            arr.append(r_blue)
        else:
            arr.append(0)

    write_sysfs(led_path, "multi_intensity", " ".join(map(str, arr)))


def thread_chassis_led_set(ev: RgbLedEvent, pending: TEvent, error: TEvent):
    try:
        chassis_led_set(ev)
    except Exception as e:
        logger.error(f"Setting leds failed with error:\n{e}")
        # Turn off support
        error.set()
    chassis_led_set(ev)
    pending.clear()


class LedDevice(Consumer):
    def __init__(self, rate_limit: float = 10, threading: bool = False) -> None:
        self.supported = is_led_supported()
        self.min_delay = 1 / rate_limit
        self.queued = None
        self.last = time.time() - self.min_delay

        self.threading = threading
        self.pending = TEvent()
        self.error = TEvent()
        self.t = None
        self.init = False

    def consume(self, events: Sequence[Event]):
        if not self.supported:
            return

        if self.error.isSet():
            self.supported = False
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

        if curr > self.last + self.min_delay and not self.pending.is_set():
            if self.threading:
                self.pending.set()
                self.t = Thread(
                    target=thread_chassis_led_set, args=(ev, self.pending, self.error)
                )
                self.t.start()
            else:
                try:
                    chassis_led_set(ev, not self.init)
                    self.init = True
                except Exception as e:
                    logger.error(f"Setting leds failed with error:\n{e}")
                    # Turn off support
                    self.supported = False
            self.last = curr
        else:
            self.queued = (ev, curr + self.min_delay)
