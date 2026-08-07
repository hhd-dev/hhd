import logging
import os
from typing import Mapping, Sequence

from hhd.plugins import Config, Context, HHDPlugin, HHDSettings, load_relative_yaml

logger = logging.getLogger(__name__)

LED_BASE = "/sys/class/leds"
LED_PATHS = {
    "power_light": os.path.join(LED_BASE, "platform::power", "brightness"),
    "power_light_sleep": os.path.join(LED_BASE, "platform::standby", "brightness"),
}


def read_led(path: str) -> bool:
    with open(path) as f:
        return int(f.read()) != 0


def write_led(path: str, enabled: bool):
    with open(path, "w") as f:
        f.write("1" if enabled else "0")


class CustomizationPlugin(HHDPlugin):
    def __init__(self, leds: Mapping[str, str]) -> None:
        self.name = "customization"
        self.priority = 76
        self.log = "cust"

        self.leds = dict(leds)
        self.prev: dict[str, bool] = {}

    def settings(self) -> HHDSettings:
        settings = load_relative_yaml("settings.yml")
        children = settings["children"]

        for name in LED_PATHS:
            if name not in self.leds:
                del children[name]

        if "power_light_sleep" not in self.leds:
            children["power_light"]["title"] = "Power Light"

        return {"gamemode": {"customization": settings}}

    def open(self, emit, context: Context):
        self.prev = {}

    def update(self, conf: Config):
        for name, path in self.leds.items():
            key = f"gamemode.customization.{name}"

            if name not in self.prev:
                try:
                    current = read_led(path)
                    conf[key] = current
                    self.prev[name] = current
                except Exception as e:
                    logger.error(f"Failed to read {name}: {e}")
                continue

            requested = conf.get(key, None)
            if requested is None or requested == self.prev[name]:
                continue

            try:
                logger.info(f"Setting {name} to {requested}")
                write_led(path, requested)
                self.prev[name] = requested
            except Exception as e:
                logger.error(f"Failed to set {name}: {e}")
                conf[key] = self.prev[name]


def autodetect(existing: Sequence[HHDPlugin]) -> Sequence[HHDPlugin]:
    if len(existing):
        return existing

    leds = {name: path for name, path in LED_PATHS.items() if os.path.isfile(path)}
    if not leds:
        return []

    return [CustomizationPlugin(leds)]
