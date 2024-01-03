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


class RogAllyControllersPlugin(HHDPlugin):
    name = "rog_ally_controllers"
    priority = 18
    log = "ally"

    def __init__(self) -> None:
        self.t = None
        self.event = None

    def open(
        self,
        emit: Emitter,
        context: Context,
    ):
        self.emit = emit
        self.context = context
        self.prev = None

    def settings(self) -> HHDSettings:
        base = {"controllers": {"rog_ally": load_relative_yaml("controllers.yml")}}
        base["controllers"]["rog_ally"]["children"]["controller_mode"].update(
            get_outputs_config()
        )
        return base

    def update(self, conf: Config):
        if conf["controllers.rog_ally"] == self.prev:
            return
        self.prev = conf["controllers.rog_ally"]

        self.start(self.prev)

    def start(self, conf):
        from .base import plugin_run

        self.close()
        self.event = Event()
        self.t = Thread(
            target=plugin_run,
            args=(conf, self.emit, self.context, self.event),
        )
        self.t.start()

    def close(self):
        if not self.event or not self.t:
            return
        self.event.set()
        self.t.join()
        self.event = None
        self.t = None


def autodetect(existing: Sequence[HHDPlugin]) -> Sequence[HHDPlugin]:
    if len(existing):
        return existing

    # Match just product number, should be enough for now
    with open("/sys/devices/virtual/dmi/id/product_name") as f:
        if not f.read().strip() == "ROG Ally RC71L_RC71L":
            return []

    return [RogAllyControllersPlugin()]
