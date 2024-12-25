from threading import Event, Thread
from typing import Any, Sequence

from hhd.controller.lib.hid import enumerate_unique
from hhd.plugins import (
    Config,
    Context,
    Emitter,
    HHDPlugin,
    get_gyro_config,
    get_outputs_config,
    get_touchpad_config,
    load_relative_yaml,
)
from hhd.plugins.settings import HHDSettings
from hhd.utils import get_distro_color, hsb_to_rgb

from .const import (
    GPD_WIN_4_8840U_MAPPINGS,
    GPD_WIN_DEFAULT_MAPPINGS,
    GPD_WIN_MAX_2_2023_MAPPINGS,
)

GPD_CONFS = {
    "G1618-03": {  # Old model, has no gyro/touchpad
        "name": "GPD Win 3",
        "touchpad": False,
        "hrtimer": False,
    },
    "G1618-04": {
        "name": "GPD Win 4",
        "hrtimer": True,
        "wincontrols": True,
        "rgb": True,
        "combo": "menu",
        "chord": "select",
    },
    "G1617-01": {
        "name": "GPD Win Mini",
        "touchpad": True,
        "wincontrols": True,
    },
    "G1619-04": {
        "name": "GPD Win Max 2 (04)",
        "hrtimer": True,
        "touchpad": True,
        "mapping": GPD_WIN_MAX_2_2023_MAPPINGS,
        "wincontrols": True,
    },
    "G1619-05": {
        "name": "GPD Win Max 2 (05)",
        "hrtimer": True,
        "touchpad": True,
        "mapping": GPD_WIN_MAX_2_2023_MAPPINGS,
        "wincontrols": True,
    },
}


def get_default_config(product_name: str):
    return {
        "name": product_name,
        "hrtimer": True,
        "untested": True,
    }


class GpdWinControllersPlugin(HHDPlugin):
    name = "gpd_win_controllers"
    priority = 18
    log = "gpdw"

    def __init__(self, dmi: str, dconf: dict) -> None:
        self.t = None
        self.should_exit = None
        self.updated = Event()
        self.started = False
        self.t = None

        self.dmi = dmi
        self.dconf = dconf
        self.name = f"gpd_win_controllers@'{dconf.get('name', 'ukn')}'"

    def open(
        self,
        emit: Emitter,
        context: Context,
    ):
        self.emit = emit
        self.context = context
        self.prev = None

    def settings(self) -> HHDSettings:
        base = {"controllers": {"gpd_win": load_relative_yaml("controllers.yml")}}
        base["controllers"]["gpd_win"]["children"]["controller_mode"].update(
            get_outputs_config(
                can_disable=True,
                has_leds=False,
                start_disabled=self.dconf.get("untested", False),
            )
        )

        # Tweak defaults for l4r4menu and main_chords
        base["controllers"]["gpd_win"]["children"]["l4r4"]["default"] = self.dconf.get(
            "combo", "r4"
        )
        base["controllers"]["gpd_win"]["children"]["main_chords"]["default"] = (
            self.dconf.get("chord", "disabled")
        )

        if self.dconf.get("touchpad", False):
            base["controllers"]["gpd_win"]["children"][
                "touchpad"
            ] = get_touchpad_config()
        else:
            del base["controllers"]["gpd_win"]["children"]["touchpad"]

        base["controllers"]["gpd_win"]["children"]["imu_axis"] = get_gyro_config(
            self.dconf.get("mapping", GPD_WIN_DEFAULT_MAPPINGS)
        )
        return base

    def update(self, conf: Config):
        new_conf = conf["controllers.gpd_win"]
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


class GpdWinControlsPlugin(HHDPlugin):
    name = "gpd_wincontrols"
    priority = 18
    log = "gpdc"

    def __init__(self, dmi: str, dconf: dict) -> None:
        self.dmi = dmi
        self.dconf = dconf
        self.name = f"gpd_wincontrols@'{dconf.get('name', 'ukn')}'"

    def open(
        self,
        emit: Emitter,
        context: Context,
    ):
        self.emit = emit
        self.context = context

    def settings(self) -> HHDSettings:
        base = {"wincontrols": {"wincontrols": load_relative_yaml("wincontrols.yml")}}

        if self.dconf.get("rgb", False):
            hue = get_distro_color()
            base["wincontrols"]["wincontrols"]["children"]["leds"]["modes"]["solid"][
                "children"
            ]["hue"]["default"] = hue
            base["wincontrols"]["wincontrols"]["children"]["leds"]["modes"]["pulse"][
                "children"
            ]["hue"]["default"] = hue
        else:
            del base["wincontrols"]["wincontrols"]["children"]["leds"]

        return base

    def update(self, conf: Config):
        if not conf.get_action(f"wincontrols.wincontrols.apply"):
            return

        from .wincontrols import (
            BACKBUTTONS_DEFAULT,
            BACKBUTTONS_HHD,
            BUTTONS_DEFAULT,
            BUTTONS_PHAWX,
            BUTTONS_TRIGGERS_DEFAULT,
            BUTTONS_TRIGGERS_STEAMOS,
            update_config,
        )

        c = conf["wincontrols.wincontrols"]
        vibration = c.get("vibration", "off")

        buttons = {}
        delays = {}
        deadzones = {}

        match c.get("mouse_mode", "unchanged"):
            case "mouse":
                buttons.update(BUTTONS_DEFAULT)
            case "wasd":
                buttons.update(BUTTONS_PHAWX)

        match c.get("mouse_mode_triggers", "unchanged"):
            case "gpd":
                buttons.update(BUTTONS_TRIGGERS_DEFAULT)
            case "steamos":
                buttons.update(BUTTONS_TRIGGERS_STEAMOS)

        match c.get("l4r4", "unchanged"):
            case "hhd":
                buttons.update(BACKBUTTONS_HHD["buttons"])
                delays.update(BACKBUTTONS_HHD["delays"])
            case "default":
                buttons.update(BACKBUTTONS_DEFAULT["buttons"])
                delays.update(BACKBUTTONS_DEFAULT["delays"])

        if c.get("deadzones.mode", "unchanged") == "custom":
            deadzones.update(c.get("deadzones.custom", {}))

        rgb_mode = "off"
        rgb_color = (0, 0, 0)
        match c.get("leds.mode", "disabled"):
            case "disabled":
                rgb_mode = "off"
            case "solid":
                rgb_mode = "constant"
                hue = c.get("leds.solid.hue", 0)
                rgb_color = tuple(hsb_to_rgb(hue, 100, 100))
            case "pulse":
                rgb_mode = "breathed"
                hue = c.get("leds.pulse.hue", 0)
                rgb_color = tuple(hsb_to_rgb(hue, 100, 100))
            case "rainbow":
                rgb_mode = "rotated"

        try:
            conf["wincontrols.wincontrols.fwver"] = update_config(
                buttons,
                delays,
                rumble=vibration,
                rgb_mode=rgb_mode,
                rgb_color=rgb_color,  # type: ignore
                deadzones=deadzones,
            )
        except Exception as e:
            conf["wincontrols.wincontrols.status"] = f"{e}"
            conf["wincontrols.wincontrols.fwver"] = f""


def autodetect(existing: Sequence[HHDPlugin]) -> Sequence[HHDPlugin]:
    if len(existing):
        return existing

    try:
        # Match just product number, should be enough for now
        with open("/sys/devices/virtual/dmi/id/product_name") as f:
            dmi = f.read().strip()
            dconf = GPD_CONFS.get(dmi, None)

            if dmi == "G1618-04":
                with open("/proc/cpuinfo") as f:
                    cpuinfo = f.read().strip()
                # 8840U has a different gyro mapping
                if "AMD Ryzen 7 8840U" in cpuinfo:
                    dconf = dict(GPD_CONFS["G1618-04"])
                    dconf["name"] = "GPD Win 4 (8840U)"
                    dconf["mapping"] = GPD_WIN_4_8840U_MAPPINGS

            if dconf:
                base: list[HHDPlugin] = [GpdWinControllersPlugin(dmi, dconf)]
                if dconf.get("wincontrols", False):
                    base.append(GpdWinControlsPlugin(dmi, dconf))
                return base

        with open("/sys/devices/virtual/dmi/id/sys_vendor") as f:
            vendor = f.read().strip().lower()
        if vendor == "gpd":
            return [GpdWinControllersPlugin(dmi, get_default_config(dmi))]
    except Exception:
        pass

    return []
