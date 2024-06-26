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
    get_gyro_state,
    get_gyro_config,
)
from hhd.plugins.settings import HHDSettings
from hhd.controller.physical.imu import BMI_MAPPINGS


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
        base = {"controllers": {"legion_go": load_relative_yaml("controllers.yml")}}
        base["controllers"]["legion_go"]["children"]["xinput"].update(
            get_outputs_config(extra_buttons='quad')
        )
        base["controllers"]["legion_go"]["children"]["touchpad"] = get_touchpad_config()
        return base

    def update(self, conf: Config):
        new_conf = conf["controllers.legion_go"]
        reset = conf["controllers.legion_go.factory_reset"].to(bool)
        conf["controllers.legion_go.factory_reset"] = False

        # Migrate old setting
        val = conf.get("controllers.legion_go.swap_legion", None)
        if val and val != "disabled":
            conf["controllers.legion_go.swap_legion"] = None
            conf["controllers.legion_go.swap_legion_v2"] = True

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


def autodetect(existing: Sequence[HHDPlugin]) -> Sequence[HHDPlugin]:
    if len(existing):
        return existing

    # Match just product number, should be enough for now
    with open("/sys/devices/virtual/dmi/id/product_name") as f:
        if not f.read().strip() == "83E1":
            return []

    return [LegionControllersPlugin()]
