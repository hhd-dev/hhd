import os
from threading import Event, Thread
from typing import Sequence

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
from hhd.plugins.utils import read_dmi

from .const import CONFS, ZOTAC_GYRO_MAPPINGS


class ZotacControllerPlugin(HHDPlugin):
    name = "zotac_controller"
    priority = 18
    log = "zotc"

    def __init__(self, dmi: str, dconf: dict) -> None:
        self.t = None
        self.should_exit = None
        self.updated = Event()
        self.started = False

        self.dmi = dmi
        self.dconf = dconf
        self.name = f"zotac_controller@'{dconf.get('name', 'ukn')}'"

    def open(
        self,
        emit: Emitter,
        context: Context,
    ):
        self.emit = emit
        self.context = context
        self.prev = None

    def settings(self) -> HHDSettings:
        base = {"controllers": {"zotac": load_relative_yaml("controllers.yml")}}
        base["controllers"]["zotac"]["children"]["controller_mode"].update(
            get_outputs_config(
                can_disable=True,
                has_leds=True,
                start_disabled=self.dconf.get("untested", False),
                extra_buttons=self.dconf.get("extra_buttons", "dual"),
            )
        )
        base["controllers"]["zotac"]["children"]["imu_axis"] = get_gyro_config(
            self.dconf.get("mapping", ZOTAC_GYRO_MAPPINGS)
        )
        return base

    def update(self, conf: Config):
        new_conf = conf["controllers.zotac"]
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

    dmi = read_dmi("product_name")
    dconf = CONFS.get(dmi, None)
    if dconf:
        return [ZotacControllerPlugin(dmi, dconf)]

    if os.environ.get("HHD_FORCE_ZOTAC", "0") == "1":
        return [ZotacControllerPlugin("forced", CONFS["ZOTAC GAMING ZONE"])]

    return []
