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
            return {"system": {"display": load_relative_yaml("settings.yml")}}
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

        curr = None
        try:
            requested = conf["system.display.brightness"].to(int)

            curr = int(
                int(read_sysfs(self.display, "brightness", None))
                * 100
                / self.max_brightness
            )

            # Set brightness
            if requested is not None and requested != self.prev:
                changed = False
                # If the change is too low the display might not make the
                # change, so while loop and increase requested values
                logger.info(f"Setting brightness to {requested}")
                while not changed and (requested >= 0 and requested <= 100):
                    write_sysfs(
                        self.display,
                        "brightness",
                        int(self.max_brightness * requested / 100),
                    )

                    # Get brightness
                    new_curr = int(
                        int(read_sysfs(self.display, "brightness", None))
                        * 100
                        / self.max_brightness
                    )
                    changed = new_curr != curr
                    curr = new_curr

                    # In case the brightness did not change
                    # increase request
                    requested_old = requested
                    if curr > requested:
                        requested -= 1
                    else:
                        requested += 1

                    if not changed:
                        logger.warning(
                            f"Could not set brightness to {requested_old}. Trying {requested}."
                        )

            conf["general.display.brightness"] = curr
            self.prev = curr
        except Exception as e:
            logger.error(f"Error while processing display settings:\n{type(e)}: {e}")
            # Set conf to avoid repeated updates
            conf["general.display.brightness"] = curr

    def close(self):
        pass


def autodetect(existing: Sequence[HHDPlugin]) -> Sequence[HHDPlugin]:
    if len(existing):
        return existing

    return [DisplayPlugin()]
