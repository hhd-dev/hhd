import logging
import os
from threading import Event, Thread
from typing import Any, Sequence

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

from .const import CONFS, DEFAULT_MAPPINGS, get_default_config

logger = logging.getLogger(__name__)


class GenericControllersPlugin(HHDPlugin):
    name = "onexplayer"
    priority = 18
    log = "oxpc"

    def __init__(self, dmi: str, dconf: dict) -> None:
        self.t = None
        self.should_exit = None
        self.updated = Event()
        self.started = False
        self.t = None

        self.dmi = dmi
        self.dconf = dconf
        self.name = f"onexplayer@'{dconf.get('name', 'ukn')}'"

    def open(
        self,
        emit: Emitter,
        context: Context,
    ):
        self.emit = emit
        self.context = context
        self.prev = None

        # Use the oxp-platform driver if available
        turbo = False
        if self.dconf.get("turbo", True) and os.path.exists(
            "/sys/devices/platform/oxp-platform/tt_toggle"
        ):
            try:
                with open("/sys/devices/platform/oxp-platform/tt_toggle", "w") as f:
                    f.write("1")
                logger.info(f"Turbo button takeover enabled")
                turbo = True

                if os.path.exists("/sys/devices/platform/oxp-platform/tt_led"):
                    with open("/sys/devices/platform/oxp-platform/tt_led", "w") as f:
                        f.write("0")
            except Exception:
                logger.warning(
                    f"Turbo takeover failed. Ensure you have the latest oxp-sensors driver installed."
                )
        self.turbo = turbo

    def notify(self, events: Sequence):
        if not self.turbo:
            return

        woke = False
        for ev in events:
            if ev["type"] == "special" and ev.get("event", None) == "wakeup":
                woke = True

        if not woke:
            return

        # We need to reset after hibernation
        try:
            logger.info(f"Turbo button takeover enabled")
            with open("/sys/devices/platform/oxp-platform/tt_toggle", "w") as f:
                f.write("1")

            if os.path.exists("/sys/devices/platform/oxp-platform/tt_led"):
                with open("/sys/devices/platform/oxp-platform/tt_led", "w") as f:
                    f.write("0")
        except Exception:
            logger.warning(
                f"Turbo takeover failed. Ensure you have the latest oxp-sensors driver installed."
            )

    def settings(self) -> HHDSettings:
        base = {"controllers": {"oxp": load_relative_yaml("controllers.yml")}}
        base["controllers"]["oxp"]["children"]["controller_mode"].update(
            get_outputs_config(
                can_disable=True,
                has_leds=self.dconf.get("rgb", True),
                start_disabled=self.dconf.get("untested", False),
                extra_buttons=self.dconf.get("extra_buttons", "dual"),
            )
        )

        base["controllers"]["oxp"]["children"]["imu_axis"] = get_gyro_config(
            self.dconf.get("mapping", DEFAULT_MAPPINGS)
        )

        if not self.dconf.get("x1", False):
            del base["controllers"]["oxp"]["children"]["volume_reverse"]
            # Maybe it is helpful for OneXFly users
            # del base["controllers"]["oxp"]["children"]["swap_face"]

        if not self.turbo:
            del base["controllers"]["oxp"]["children"]["extra_buttons"]
            del base["controllers"]["oxp"]["children"]["turbo_reboots"]

        return base

    def update(self, conf: Config):
        new_conf = conf["controllers.oxp"]
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
                self.turbo,
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

        if self.turbo:
            # Disable turbo button takeover
            try:
                with open("/sys/devices/platform/oxp-platform/tt_toggle", "w") as f:
                    f.write("0")
            except Exception:
                pass


def autodetect(existing: Sequence[HHDPlugin]) -> Sequence[HHDPlugin]:
    if len(existing):
        return existing

    # Match just product name
    # if a device exists here its officially supported
    with open("/sys/devices/virtual/dmi/id/product_name") as f:
        dmi = f.read().strip()

    dconf = CONFS.get(dmi, None)
    if dconf:
        return [GenericControllersPlugin(dmi, dconf)]

    # Begin hw agnostic dmi match
    if "ONEXPLAYER" in dmi:
        return [GenericControllersPlugin(dmi, get_default_config(dmi, "ONEXPLAYER"))]

    return []
