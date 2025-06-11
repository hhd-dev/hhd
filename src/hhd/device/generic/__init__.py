from threading import Event, Thread
from typing import Any, Sequence

from hhd.controller.physical.rgb import is_led_supported
from hhd.plugins import (
    Config,
    Context,
    Emitter,
    HHDPlugin,
    get_gyro_config,
    get_outputs_config,
    load_relative_yaml,
)
from hhd.plugins.settings import HHDSettings

from .const import CONFS, DEFAULT_MAPPINGS, get_default_config


class GenericControllersPlugin(HHDPlugin):
    name = "generic_controllers"
    priority = 18
    log = "genc"

    def __init__(self, dmi: str, dconf: dict) -> None:
        self.t = None
        self.should_exit = None
        self.updated = Event()
        self.started = False
        self.t = None

        self.dmi = dmi
        self.dconf = dconf
        self.name = f"generic_controllers@'{dconf.get('name', 'ukn')}'"

    def open(
        self,
        emit: Emitter,
        context: Context,
    ):
        self.emit = emit
        self.context = context
        self.prev = None

    def settings(self) -> HHDSettings:
        base = {"controllers": {"handheld": load_relative_yaml("controllers.yml")}}
        base["controllers"]["handheld"]["children"]["controller_mode"].update(
            get_outputs_config(
                can_disable=True,
                has_leds=is_led_supported(),
                start_disabled=self.dconf.get("untested", False),
                extra_buttons=self.dconf.get("extra_buttons", "dual"),
            )
        )

        if self.dconf.get("display_gyro", True):
            base["controllers"]["handheld"]["children"]["imu_axis"] = get_gyro_config(
                self.dconf.get("mapping", DEFAULT_MAPPINGS)
            )
        else:
            del base["controllers"]["handheld"]["children"]["imu_axis"]
            del base["controllers"]["handheld"]["children"]["imu"]

        return base

    def update(self, conf: Config):
        new_conf = conf["controllers.handheld"]
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

    dconf = CONFS.get(dmi, None)
    if dconf:
        return [GenericControllersPlugin(dmi, dconf)]

    try:
        with open("/sys/devices/virtual/dmi/id/sys_vendor") as f:
            vendor = f.read().strip().lower()
        if vendor == "ayn":
            return [GenericControllersPlugin(dmi, get_default_config(dmi, "AYN"))]
    except Exception:
        pass

    # Fallback to chassis vendor for aya
    try:
        with open("/sys/class/dmi/id/board_vendor") as f:
            vendor = f.read().lower().strip()

        if "ayaneo" in vendor:
            return [GenericControllersPlugin(dmi, get_default_config(dmi, "AYA"))]
    except Exception:
        return []

    return []
