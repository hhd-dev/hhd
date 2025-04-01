from threading import Event, Thread
from typing import Sequence
import os

from hhd.controller.physical.rgb import is_led_supported
from hhd.plugins import (
    Config,
    Context,
    Emitter,
    HHDPlugin,
    get_gyro_config,
    get_outputs_config,
    load_relative_yaml,
)
from hhd.plugins.settings import HHDSettings
import logging

from .const import CONFS

logger = logging.getLogger(__name__)


class ClawControllerPlugin(HHDPlugin):
    name = "claw_controller"
    priority = 18
    log = "claw"

    def __init__(self, dmi: str, dconf: dict) -> None:
        self.t = None
        self.should_exit = None
        self.updated = Event()
        self.woke_up = Event()
        self.started = False
        self.t = None

        self.dmi = dmi
        self.dconf = dconf
        self.name = f"claw_controller@'{dconf.get('name', 'ukn')}'"

    def open(
        self,
        emit: Emitter,
        context: Context,
    ):
        self.emit = emit
        self.context = context
        self.prev = None

    def settings(self) -> HHDSettings:
        base = {"controllers": {"claw": load_relative_yaml("controllers.yml")}}
        base["controllers"]["claw"]["children"]["controller_mode"].update(
            get_outputs_config(
                can_disable=True,
                has_leds=is_led_supported(),
                start_disabled=self.dconf.get("untested", False),
                extra_buttons=self.dconf.get("extra_buttons", "dual"),
            )
        )

        return base

    def update(self, conf: Config):
        new_conf = conf["controllers.claw"]
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
                self.woke_up,
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
    
    def notify(self, events: Sequence):
        for ev in events:
            if ev["type"] == "special" and ev.get("event", None) == "wakeup":
                self.woke_up.set()


def autodetect(existing: Sequence[HHDPlugin]) -> Sequence[HHDPlugin]:
    if len(existing):
        return existing

    # Match just product name
    # if a device exists here its officially supported
    with open("/sys/devices/virtual/dmi/id/product_name") as f:
        dmi = f.read().strip()

    dconf = CONFS.get(dmi, None)
    if dconf:
        return [ClawControllerPlugin(dmi, dconf)]

    if os.environ.get("HHD_FORCE_CLAW", "0") == "1":
        return [ClawControllerPlugin("forced", CONFS["Claw 8 AI+ A2VM"])]

    return []
