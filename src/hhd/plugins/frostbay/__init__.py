from threading import Event, Thread
from typing import Sequence

from hhd.plugins import Config, HHDPlugin, load_relative_yaml
from hhd.plugins.settings import HHDSettings


class FrostbayPlugin(HHDPlugin):
    name = "frostbay"
    priority = 45
    log = "frst"

    def __init__(self) -> None:
        self.t = None
        self.should_exit = None
        self.updated = Event()
        self.want_on = Event()        # set = user wants device ON
        self.force_on_apply = Event() # set = resend current ON target even if unchanged
        self.status_ref = ["Disconnected"]  # worker writes here; update() reads
        self.telemetry_ref = {
            "running_state": "Unknown",
            "flow": "--",
            "water_temp_in": "--",
            "water_temp_out": "--",
        }
        self.started = False
        self.prev = None

    def settings(self) -> HHDSettings:
        return {"cooling": {"frostbay": load_relative_yaml("frostbay.yml")}}

    def update(self, conf: Config):
        # Reflect worker status into root conf every call
        conf["cooling.frostbay.ble_status"] = self.status_ref[0]
        conf["cooling.frostbay.running_state"] = self.telemetry_ref["running_state"]
        conf["cooling.frostbay.flow"] = self.telemetry_ref["flow"]
        conf["cooling.frostbay.water_temp_in"] = self.telemetry_ref["water_temp_in"]
        conf["cooling.frostbay.water_temp_out"] = self.telemetry_ref["water_temp_out"]

        # Handle action buttons
        if conf.get_action("cooling.frostbay.turn_on"):
            self.want_on.set()
            self.force_on_apply.set()
            self.updated.set()
        if conf.get_action("cooling.frostbay.turn_off"):
            self.want_on.clear()
            self.force_on_apply.clear()
            self.updated.set()

        # Keep conf subtree in sync for fan/pump settings
        new_conf = conf["cooling.frostbay"]
        if self.prev is None:
            self.prev = new_conf
            self.start(self.prev)
        else:
            if new_conf != self.prev:
                self.prev.update(new_conf.conf)
                self.updated.set()

    def start(self, conf):
        from .base import plugin_run

        if self.started:
            return

        self.should_exit = Event()
        self.t = Thread(
            target=plugin_run,
            args=(
                conf,
                self.should_exit,
                self.updated,
                self.want_on,
                self.force_on_apply,
                self.status_ref,
                self.telemetry_ref,
            ),
        )
        self.t.start()
        self.started = True

    def close(self):
        if not self.should_exit or not self.t:
            return
        self.should_exit.set()
        self.t.join()
        self.should_exit = None
        self.t = None
        self.started = False


def autodetect(existing: Sequence[HHDPlugin]) -> Sequence[HHDPlugin]:
    if len(existing):
        return existing

    return [FrostbayPlugin()]

