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

from .const import CONFS, DEFAULT_MAPPINGS


class AyaneoControllersPlugin(HHDPlugin):
    name = "ayaneo_controllers"
    priority = 18
    log = "ayac"

    def __init__(self, dmi: str, dconf: dict) -> None:
        self.t = None
        self.should_exit = None
        self.updated = Event()
        self.started = False
        self.t = None

        self.dmi = dmi
        self.dconf = dconf
        self.magic_modules = dconf.get("magic_modules", False)
        self.name = f"ayaneo_controllers@'{dconf.get('name', 'ukn')}'"

        self.config = Config()

    def open(
        self,
        emit: Emitter,
        context: Context,
    ):
        self.emit = emit
        self.context = context
        self.prev = None

    def settings(self) -> HHDSettings:
        if self.magic_modules:
            base = {
                "controllers": {
                    "ayaneo": load_relative_yaml("controllers.yml"),
                },
                "magic_modules": {
                    "magic_modules": load_relative_yaml("modules.yml"),
                },
            }
        else:
            base = {
                "controllers": {
                    "ayaneo": load_relative_yaml("controllers.yml"),
                }
            }

        base["controllers"]["ayaneo"]["children"]["controller_mode"].update(
            get_outputs_config(
                can_disable=True,
                has_leds=self.dconf.get("rgb", False),
                start_disabled=self.dconf.get("untested", False),
                extra_buttons=self.dconf.get("extra_buttons", "quad"),
                noob_default=False,
            )
        )

        if self.dconf.get("display_gyro", True):
            base["controllers"]["ayaneo"]["children"]["imu_axis"] = get_gyro_config(
                self.dconf.get("mapping", DEFAULT_MAPPINGS)
            )
        else:
            del base["controllers"]["ayaneo"]["children"]["imu_axis"]
            del base["controllers"]["ayaneo"]["children"]["imu"]

        return base

    def update(self, conf: Config):
        new_conf = conf["controllers.ayaneo"]

        if self.magic_modules:
            pop_both = conf.get_action("magic_modules.magic_modules.pop_both")
            pop_left = conf.get_action("magic_modules.magic_modules.pop_left")
            pop_right = conf.get_action("magic_modules.magic_modules.pop_right")
            reset = conf.get_action("magic_modules.magic_modules.reset")

            conf["magic_modules.magic_modules.info_right"] = self.config.get(
                "info_right", None
            )
            conf["magic_modules.magic_modules.info_left"] = self.config.get(
                "info_left", None
            )
        else:
            pop_both = False
            pop_left = False
            pop_right = False
            reset = False

        if (
            new_conf == self.prev
            and not pop_both
            and not pop_left
            and not pop_right
            and not reset
        ):
            return
        if self.prev is None:
            self.prev = new_conf
        else:
            self.prev.update(new_conf.conf)

        if pop_both:
            pop = "both"
        elif pop_left:
            pop = "left"
        elif pop_right:
            pop = "right"
        else:
            pop = None

        if pop_both or pop_left or pop_right or reset:
            self.started = False
        else:
            self.updated.set()
        self.start(self.prev, pop=pop, reset=reset)

    def start(self, conf, pop=None, reset=False):
        from .base import plugin_run

        if self.started:
            return
        self.started = True

        self.close()
        self.should_exit = Event()
        self.config["pop"] = pop
        self.config["reset"] = reset
        self.t = Thread(
            target=plugin_run,
            args=(
                conf,
                self.emit,
                self.context,
                self.should_exit,
                self.updated,
                self.dconf,
                self.config,
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

    # Match just product name
    # if a device exists here its officially supported
    with open("/sys/devices/virtual/dmi/id/product_name") as f:
        dmi = f.read().strip()

    dconf = CONFS.get(dmi, None)
    if dconf:
        return [AyaneoControllersPlugin(dmi, dconf)]

    return []
