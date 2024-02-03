from threading import Event, Thread
from typing import Any, Sequence

from hhd.plugins import (
    Config,
    Context,
    Emitter,
    HHDPlugin,
    load_relative_yaml,
    get_outputs_config,
)
from hhd.plugins.settings import HHDSettings


AOKZOE_CONFS = {
    "AOKZOE A1 AR07": {"name": "AOKZOE A1", "hrtimer": True},
    "AOKZOE A1 Pro": {"name": "AOKZOE A1 Pro", "hrtimer": True},
}


def get_default_config(product_name: str):
    return {
        "name": product_name,
        "hrtimer": True,
        "untested": True,
    }


class AokzoeControllersPlugin(HHDPlugin):
    name = "aokzoe_controllers"
    priority = 18
    log = "zokz"

    def __init__(self, dmi: str, dconf: dict) -> None:
        self.t = None
        self.should_exit = None
        self.updated = Event()
        self.started = False
        self.t = None

        self.dmi = dmi
        self.dconf = dconf
        self.name = f"aokzoe_controllers@'{dconf.get('name', 'ukn')}'"

    def open(
        self,
        emit: Emitter,
        context: Context,
    ):
        self.emit = emit
        self.context = context
        self.prev = None

    def settings(self) -> HHDSettings:
        base = {"controllers": {"aokzoe": load_relative_yaml("controllers.yml")}}
        base["controllers"]["aokzoe"]["children"]["controller_mode"].update(
            get_outputs_config(can_disable=False, has_leds=False)
        )

        return base

    def update(self, conf: Config):
        new_conf = conf["controllers.aokzoe"]
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
    
    dconf = AOKZOE_CONFS.get(dmi, None)
    if dconf:
        return [AokzoeControllersPlugin(dmi, dconf)]

    return []
