from threading import Event, Thread
from typing import Any, Sequence
from .const import AYANEO_AIR_PLUS_MAPPINGS, AYANEO_DEFAULT_MAPPINGS

from hhd.plugins import (
    Config,
    Context,
    Emitter,
    HHDPlugin,
    load_relative_yaml,
    get_outputs_config,
    get_touchpad_config,
    get_gyro_config,
)
from hhd.plugins.settings import HHDSettings


AYANEO_CONFS = {
    "AIR Plus": {
        "name": "AYANEO AIR Plus",
        "hrtimer": True,
        "mapping": AYANEO_AIR_PLUS_MAPPINGS,
    },
    "AYANEO 2": {"name": "AYANEO 2", "hrtimer": True},
    "AYANEO 2S": {"name": "AYANEO S2", "hrtimer": True},
    "GEEK": {"name": "AYANEO GEEK", "hrtimer": True},
    "GEEK 1S": {"name": "AYANEO GEEK 1S", "hrtimer": True},
}


def get_default_config(product_name: str):
    return {
        "name": product_name,
        "hrtimer": True,
        "untested": True,
    }


class AyaneoControllersPlugin(HHDPlugin):
    name = "ayaneo_controllers"
    priority = 18
    log = "ayan"

    def __init__(self, dmi: str, dconf: dict) -> None:
        self.t = None
        self.should_exit = None
        self.updated = Event()
        self.started = False
        self.t = None

        self.dmi = dmi
        self.dconf = dconf
        self.name = f"ayaneo_controllers@'{dconf.get('name', 'ukn')}'"

    def open(
        self,
        emit: Emitter,
        context: Context,
    ):
        self.emit = emit
        self.context = context
        self.prev = None

    def settings(self) -> HHDSettings:
        base = {"controllers": {"ayaneo": load_relative_yaml("controllers.yml")}}
        base["controllers"]["ayaneo"]["children"]["controller_mode"].update(
            get_outputs_config(
                can_disable=True,
                has_leds=False,
                start_disabled=self.dconf.get("untested", False),
            )
        )

        if self.dconf.get("touchpad", False):
            base["controllers"]["ayaneo"]["children"][
                "touchpad"
            ] = get_touchpad_config()
        else:
            del base["controllers"]["ayaneo"]["children"]["touchpad"]

        base["controllers"]["ayaneo"]["children"]["gyro"] = get_gyro_config(
            self.dconf.get("mapping", AYANEO_DEFAULT_MAPPINGS)
        )

        return base

    def update(self, conf: Config):
        new_conf = conf["controllers.ayaneo"]
        if new_conf == self.prev:
            return
        if self.prev is None:
            self.prev = new_conf
        else:
            self.prev.update(new_conf.conf)

        self.updated.set()
        self.start(self.prev)

    def start(self, conf):
        from .base import plugin_run

        if self.started:
            return
        self.started = True

        self.close()
        self.should_exit = Event()
        self.t = Thread(
            target=plugin_run,
            args=(
                conf,
                self.emit,
                self.context,
                self.should_exit,
                self.updated,
                self.dconf,
            ),
        )
        self.t.start()

    def close(self):
        if not self.should_exit or not self.t:
            return
        self.should_exit.set()
        self.t.join()
        self.should_exit = None
        self.t = None


def autodetect(existing: Sequence[HHDPlugin]) -> Sequence[HHDPlugin]:
    if len(existing):
        return existing

    # Match just product name
    # if a device exists here its officially supported
    with open("/sys/devices/virtual/dmi/id/product_name") as f:
        dmi = f.read().strip()

    dconf = AYANEO_CONFS.get(dmi, None)
    if dconf:
        return [AyaneoControllersPlugin(dmi, dconf)]

    # Fallback to chassis vendor since aya contains no usb devices
    try:
        with open("/sys/class/dmi/id/board_vendor") as f:
            vendor = f.read().lower().strip()

        if "ayaneo" in vendor:
            return [AyaneoControllersPlugin(dmi, get_default_config(dmi))]
    except Exception:
        return []

    return []
