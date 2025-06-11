from threading import Event, Thread

from hhd.plugins import (
    Config,
    Context,
    Emitter,
    HHDPlugin,
    load_relative_yaml,
    get_outputs_config,
)
from hhd.plugins.settings import HHDSettings


class LegionGoSControllerPlugin(HHDPlugin):
    name = "legion_go_slim_controller"
    priority = 18
    log = "lgos"

    def __init__(self, dconf) -> None:
        self.dconf = dconf
        self.t = None
        self.should_exit = None
        self.updated = Event()
        self.started = False
        self.t = None
        self.prev = None

    def open(
        self,
        emit: Emitter,
        context: Context,
    ):
        self.emit = emit
        self.context = context
        self.prev = None

    def settings(self) -> HHDSettings:
        base = {"controllers": {"legion_gos": load_relative_yaml("controller.yml")}}
        base["controllers"]["legion_gos"]["children"]["xinput"].update(
            get_outputs_config(extra_buttons="dual")
        )
        return base

    def update(self, conf: Config):
        new_conf = conf["controllers.legion_gos"]
        reset = conf["controllers.legion_gos.factory_reset"].to(bool)
        conf["controllers.legion_gos.factory_reset"] = False

        if new_conf == self.prev:
            return
        if self.prev is None:
            self.prev = new_conf
        else:
            self.prev.update(new_conf.conf)

        if reset:
            self.started = False
        else:
            self.updated.set()
        self.start(self.prev, reset)

    def start(self, conf, reset=False):
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
                {"reset": reset},
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
