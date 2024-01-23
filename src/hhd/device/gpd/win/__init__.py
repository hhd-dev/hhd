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
)
from hhd.plugins.settings import HHDSettings

GPD_WMIS = {
    "G1618-04": "GPD Win 4",
    "G1617-01": "GPD Win Mini",
    "G1619-05": "GPD Win Max 2 2023",
}

GPD_CONFS = {"G1619-05": {"hrtimer": True}, "G1618-04": {"hrtimer": True}}

GPD_TOUCHPAD = ["G1617-01", "G1619-05"]


class GpdWinControllersPlugin(HHDPlugin):
    name = "gpd_win_controllers"
    priority = 18
    log = "gpdw"

    def __init__(self, dmi: str, name: str) -> None:
        self.t = None
        self.should_exit = None
        self.updated = Event()
        self.started = False
        self.t = None

        self.dmi = dmi
        self.name = f"gpd_win_controllers@'{name}'"

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
            get_outputs_config(can_disable=False, has_leds=False)
        )

        if self.dmi in GPD_TOUCHPAD:
            base["controllers"]["gpd_win"]["children"][
                "touchpad"
            ] = get_touchpad_config()
        else:
            del base["controllers"]["gpd_win"]["children"]["touchpad"]

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
                GPD_CONFS.get(self.dmi, {}),
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
        name = GPD_WMIS.get(dmi)
        if not name:
            return []

    return [GpdWinControllersPlugin(dmi, name)]
