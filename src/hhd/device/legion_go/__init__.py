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


class LegionControllersPlugin(HHDPlugin):
    name = "legion_go_controllers"
    priority = 18
    log = "llgo"

    def __init__(self) -> None:
        self.t = None
        self.should_exit = None
        self.updated = Event()
        self.started = False
        self.t = None

    def open(
        self,
        emit: Emitter,
        context: Context,
    ):
        self.emit = emit
        self.context = context
        self.prev = None

    def settings(self) -> HHDSettings:
        base = {"controllers": {"legion_go": load_relative_yaml("controllers.yml")}}
        base["controllers"]["legion_go"]["children"]["xinput"].update(
            get_outputs_config()
        )
        return base

    def update(self, conf: Config):
        if conf["controllers.legion_go"] == self.prev:
            return
        self.prev = conf["controllers.legion_go"]

        self.start(self.prev)
        conf.update(self.prev.conf)
        self.updated.set()

    def start(self, conf):
        from .base import plugin_run

        if self.started:
            return
        self.started = True

        self.close()
        self.should_exit = Event()
        self.t = Thread(
            target=plugin_run,
            args=(conf, self.emit, self.context, self.should_exit, self.updated),
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
        if not f.read().strip() == "83E1":
            return []

    return [LegionControllersPlugin()]
