from threading import Event, Thread
from typing import Any, Sequence

from hhd.plugins import Config, Context, Emitter, HHDPlugin, load_relative_yaml
from hhd.plugins.settings import HHDSettings


class LegionControllersPlugin(HHDPlugin):
    name = "legion_go_controllers"
    priority = 18

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

    def settings(self) -> HHDSettings:
        return {"controllers": {"legion_go": load_relative_yaml("controllers.yaml")}}

    def start(self, conf):
        from .base import plugin_run

        self.event = Event()
        self.t = Thread(
            target=plugin_run, args=(conf, self.emit, self.context, self.event)
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
        if not f.read().strip() == "83E1":
            return []

    return [LegionControllersPlugin()]
