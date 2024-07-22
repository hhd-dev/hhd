from threading import Event, Thread
from typing import Any, Sequence

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
from hhd.controller.lib.hid import enumerate_unique

from .const import GPD_WIN_MAX_2_2023_MAPPINGS, GPD_WIN_DEFAULT_MAPPINGS

GPD_CONFS = {
    "G1618-03": {  # Old model, has no gyro/touchpad
        "name": "GPD Win 3",
        "touchpad": False,
        "hrtimer": False,
    },
    "G1618-04": {"name": "GPD Win 4", "hrtimer": True},
    "G1617-01": {"name": "GPD Win Mini", "touchpad": True},
    "G1619-04": {
        "name": "GPD Win Max 2 (04)",
        "hrtimer": True,
        "touchpad": True,
        "mapping": GPD_WIN_MAX_2_2023_MAPPINGS,
    },
    "G1619-05": {
        "name": "GPD Win Max 2 (05)",
        "hrtimer": True,
        "touchpad": True,
        "mapping": GPD_WIN_MAX_2_2023_MAPPINGS,
    },
}


def get_default_config(product_name: str):
    return {
        "name": product_name,
        "hrtimer": True,
        "untested": True,
    }


class GpdWinControllersPlugin(HHDPlugin):
    name = "gpd_win_controllers"
    priority = 18
    log = "gpdw"

    def __init__(self, dmi: str, dconf: dict) -> None:
        self.t = None
        self.should_exit = None
        self.updated = Event()
        self.started = False
        self.t = None

        self.dmi = dmi
        self.dconf = dconf
        self.name = f"gpd_win_controllers@'{dconf.get('name', 'ukn')}'"

    def open(
        self,
        emit: Emitter,
        context: Context,
    ):
        self.emit = emit
        self.context = context
        self.prev = None

    def settings(self) -> HHDSettings:
        base = {"controllers": {"gpd_win": load_relative_yaml("controllers.yml")}}
        base["controllers"]["gpd_win"]["children"]["controller_mode"].update(
            get_outputs_config(
                can_disable=True,
                has_leds=False,
                start_disabled=self.dconf.get("untested", False),
            )
        )

        if self.dconf.get("touchpad", False):
            base["controllers"]["gpd_win"]["children"][
                "touchpad"
            ] = get_touchpad_config()
        else:
            del base["controllers"]["gpd_win"]["children"]["touchpad"]

        base["controllers"]["gpd_win"]["children"]["imu_axis"] = get_gyro_config(
            self.dconf.get("mapping", GPD_WIN_DEFAULT_MAPPINGS)
        )
        return base

    def update(self, conf: Config):
        new_conf = conf["controllers.gpd_win"]
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

    # Match just product number, should be enough for now
    with open("/sys/devices/virtual/dmi/id/product_name") as f:
        dmi = f.read().strip()
        dconf = GPD_CONFS.get(dmi, None)
        if dconf:
            return [GpdWinControllersPlugin(dmi, dconf)]

    try:
        with open("/sys/devices/virtual/dmi/id/sys_vendor") as f:
            vendor = f.read().strip().lower()
        if vendor == "gpd":
            return [GpdWinControllersPlugin(dmi, get_default_config(dmi))]
    except Exception:
        pass

    return []
