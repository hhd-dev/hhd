from typing import Any, Sequence, TYPE_CHECKING
import os
from hhd.plugins import (
    HHDPlugin,
    Context,
)
from time import sleep
from hhd.plugins import HHDSettings, load_relative_yaml
import logging

from hhd.plugins.conf import Config

logger = logging.getLogger(__name__)
BACKLIGHT_DIR = "/sys/class/backlight/"
LEVELS = [0, 5, 10, 15, 20, 35, 50, 75, 90, 100]


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


class DisplayPlugin(HHDPlugin):
    def __init__(self) -> None:
        self.name = f"displayd"
        self.priority = 4
        self.log = "disp"

        self.display = None
        self.max_brightness = 255

    def settings(self) -> HHDSettings:
        if self.display:
            s = {"general": {"display": load_relative_yaml("settings.yml")}}
            s["general"]["display"]["children"]["brightness"]["options"] = LEVELS
            return s
        else:
            return {}

    def open(
        self,
        emit,
        context: Context,
    ):
        self.display = None
        self.prev = None
        for d in os.listdir(BACKLIGHT_DIR):
            ddir = os.path.join(BACKLIGHT_DIR, d)
            try:
                read_sysfs(ddir, "brightness")
                max_bright = int(read_sysfs(ddir, "max_brightness"))
                self.display = ddir
                self.max_brightness = max_bright
            except Exception:
                pass

        if self.display is None:
            logger.warning(f"Display with variable brightness not found. Exitting.")

    def update(self, conf: Config):
        if not self.display:
            return

        try:
            requested = conf["general.display.brightness"].to(float | None)
            # Set brightness
            if requested and requested != -1 and requested != self.prev:
                logger.info(f"Setting brightness to {requested}")
                write_sysfs(
                    self.display,
                    "brightness",
                    int(self.max_brightness * requested / 100),
                )
                # Wait a bit
                sleep(0.1)

            # Get brightness
            curr = (
                int(read_sysfs(self.display, "brightness", None))
                * 100
                / self.max_brightness
            )
            discr = min(LEVELS, key=lambda x: abs(x - curr))
            conf["general.display.brightness"] = discr
            self.prev = discr
        except Exception as e:
            logger.error(f"Error while processing display settings:\n{type(e)}: {e}")

    def close(self):
        pass


def autodetect(existing: Sequence[HHDPlugin]) -> Sequence[HHDPlugin]:
    if len(existing):
        return existing

    return [DisplayPlugin()]
