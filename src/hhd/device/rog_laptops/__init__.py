from threading import Event as TEvent, Thread
from typing import Sequence

from hhd.plugins import (
    Config,
    Context,
    Emitter,
    Event,
    HHDPlugin,
    load_relative_yaml,
    get_outputs_config,
)
from hhd.plugins.settings import HHDSettings


class RogLaptopControllersPlugin(HHDPlugin):
    name = "rog_laptop_controllers"
    priority = 18
    log = "rog_laptop"

    def __init__(self, target_device: str, report_id: int) -> None:
        self.t = None
        self.should_exit = None
        self.updated = TEvent()
        self.started = False
        self.t = None
        self.target_device = target_device
        self.report_id = report_id

    def open(
        self,
        emit: Emitter,
        context: Context,
    ):
        self.emit = emit
        self.context = context
        self.prev = None

    def settings(self) -> HHDSettings:
        base = {"controllers": {"rog_laptops": load_relative_yaml("controllers.yml")}}
        base["controllers"]["rog_laptops"]["children"]["controller_mode"].update(
            get_outputs_config(
                can_disable=True,
                extra_buttons="none",
                noob_default=True,
                start_disabled=True,
            )
        )
        return base

    def update(self, conf: Config):
        import logging
        logger = logging.getLogger(__name__)
        
        new_conf = conf["controllers.rog_laptops"]
        
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
        self.should_exit = TEvent()
        self.t = Thread(
            target=plugin_run,
            args=(
                conf,
                self.emit,
                self.context,
                self.should_exit,
                self.updated,
                self.target_device,
                self.report_id,
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

    # Match product number
    with open("/sys/devices/virtual/dmi/id/product_name") as f:
        dmi = f.read().strip()

    # GA403UI
    if "GA403" in dmi:
        return [RogLaptopControllersPlugin(target_device="GA403", report_id=0x5D)]

    return []
