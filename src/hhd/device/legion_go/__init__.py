from threading import Event, Thread
from typing import Any, Sequence

from hhd.plugins import (
    Config,
    Context,
    HHDPlugin,
    get_relative_fn,
    Emitter,
)


class LegionControllersPlugin(HHDPlugin):
    name = "legion_go_controllers"
    priority = 18

    def open(
        self,
        conf: Config,
        emit: Emitter,
        context: Context,
    ):
        from .base import plugin_run

        self.event = Event()
        self.t = Thread(target=plugin_run, args=(conf, emit, context, self.event))
        self.t.start()

    def close(self):
        self.event.set()
        self.t.join()


def autodetect(existing: Sequence[HHDPlugin]) -> Sequence[HHDPlugin]:
    if len(existing):
        return []

    # Match just product number, should be enough for now
    with open("/sys/devices/virtual/dmi/id/product_name") as f:
        if not f.read().strip() == "83E1":
            return []

    return [LegionControllersPlugin()]
