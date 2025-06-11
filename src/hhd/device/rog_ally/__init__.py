from threading import Event, Thread
from typing import Any, Sequence

from hhd.plugins import (
    Config,
    Context,
    Emitter,
    HHDPlugin,
    load_relative_yaml,
    get_outputs_config,
    get_limits_config,
    fix_limits,
)
from hhd.plugins.settings import HHDSettings


class RogAllyControllersPlugin(HHDPlugin):
    name = "rog_ally_controllers"
    priority = 18
    log = "ally"

    def __init__(self, ally_x: bool = False) -> None:
        self.t = None
        self.should_exit = None
        self.updated = Event()
        self.started = False
        self.t = None
        self.ally_x = ally_x

    def open(
        self,
        emit: Emitter,
        context: Context,
    ):
        self.emit = emit
        self.context = context
        self.prev = None

    def settings(self) -> HHDSettings:
        from .base import LIMIT_DEFAULTS

        base = {"controllers": {"rog_ally": load_relative_yaml("controllers.yml")}}
        base["controllers"]["rog_ally"]["children"]["controller_mode"].update(
            get_outputs_config(can_disable=False)
        )
        base["controllers"]["rog_ally"]["children"]["limits"] = get_limits_config(
            LIMIT_DEFAULTS(self.ally_x)
        )
        return base

    def update(self, conf: Config):
        from .base import LIMIT_DEFAULTS

        fix_limits(conf, "controllers.rog_ally.limits", LIMIT_DEFAULTS(self.ally_x))

        new_conf = conf["controllers.rog_ally"]
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
                self.ally_x,
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
        # Different variants of the ally can have an additional _RC71L or not
        dmi = f.read().strip()

    # First gen ally
    # ROG Ally RC71L_Action or something else
    if "ROG Ally RC71L" in dmi:
        return [RogAllyControllersPlugin()]

    # Ally X
    # ROG Ally X RC72LA_RC72LA_000123206
    if "ROG Ally X RC72LA" in dmi:
        return [RogAllyControllersPlugin(ally_x=True)]

    return []
