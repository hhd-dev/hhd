import logging
import time
from typing import Literal, Sequence, cast

from hhd.controller import DEBUG_MODE, Event, RgbMode
from hhd.plugins import Config, Context, HHDPlugin, load_relative_yaml
from hhd.utils import get_distro_color, hsb_to_rgb

logger = logging.getLogger(__name__)

RGB_SET_TIMES = 2
RGB_SET_INTERVAL = 5
RGB_MIN_INTERVAL = 0.1
RGB_QUEUE_RGB = 1.5


class RgbPlugin(HHDPlugin):
    def __init__(self) -> None:
        self.name = f"controller_rgb"
        self.priority = 15
        self.log = "LEDS"

        self.modes = None
        self.controller = False
        self.loaded = False
        self.enabled = False
        self.last_set = 0
        self.queue_leds = None

        self.init_count = 0
        self.init_last = 0
        self.init = True
        self.uniq = None
        self.restore = None
        self.last_ev = None

        self.prev = None

    def open(
        self,
        emit,
        context: Context,
    ):
        self.started = False
        self.emit = emit

    def notify(self, events):
        for ev in events:
            # Certain ayaneo devices reset LEDs when being
            # plugged in
            if ev["type"] == "acpi" and ev["event"] in ("ac", "dc"):
                self.init = True
                self.init_count = RGB_SET_TIMES - 1
            elif ev["type"] == "special":
                match ev["event"]:
                    case "tdp_cycle_quiet":
                        color = (0, 0, 255)
                    case "tdp_cycle_balanced":
                        color = (255, 255, 255)
                    case "tdp_cycle_performance":
                        color = (255, 0, 0)
                    case "tdp_cycle_custom":
                        color = (157, 0, 255)
                    case _:
                        color = None

                if color:
                    red, green, blue = color
                    curr = time.time()
                    evs: Sequence[tuple[Event, float]] = []
                    # Set color based on mode on low brightness
                    if not self.controller:
                        evs.append(
                            (
                                {
                                    "type": "led",
                                    "initialize": True,  # Always initialize, saves problems on the ally
                                    "code": "main",
                                    "mode": "solid",
                                    "direction": "left",
                                    "brightness": 0.33,
                                    "brightnessd": "low",
                                    "speed": 0,
                                    "speedd": "low",
                                    "red": red,
                                    "green": green,
                                    "blue": blue,
                                    "red2": 0,
                                    "green2": 0,
                                    "blue2": 0,
                                    "oxp": None,
                                },
                                curr,
                            ),
                        )
                    # Add short vibration
                    evs.append(
                        (
                            {
                                "type": "rumble",
                                "code": "main",
                                "strong_magnitude": 0.2,
                                "weak_magnitude": 0.2,
                            },
                            curr,
                        ),
                    )
                    evs.append(
                        (
                            {
                                "type": "rumble",
                                "code": "main",
                                "strong_magnitude": 0,
                                "weak_magnitude": 0,
                            },
                            curr + 0.1,
                        ),
                    )
                    # Restore old color
                    if not self.controller and self.last_ev:
                        evs.append((self.last_ev, curr + 3))

                    self.emit.inject_timed(evs)

    def settings(self):
        if not self.modes:
            self.loaded = False
            return {}
        self.loaded = True

        # If RGB support is disabled
        # return enable option only
        base = load_relative_yaml("settings.yml")
        if not self.enabled:
            del base["rgb"]
            return base

        if self.controller:
            # Remove RGB settings because the controller has control
            del base["rgb"]["handheld"]["children"]["mode"]
        else:
            # Remove disclaimer
            del base["rgb"]["handheld"]["children"]["controller"]
            modes = load_relative_yaml("modes.yml")
            capabilities = load_relative_yaml("capabilities.yml")

            # Set a sane default color
            dc = get_distro_color()

            supported = {}
            for mode, caps in self.modes.items():
                if mode in modes:
                    m = modes[mode]
                    m["children"] = {}
                    for cap in caps:
                        m["children"].update(
                            {k: dict(v) for k, v in capabilities[cap].items()}
                        )
                        if cap == "color":
                            m["children"]["hue"]["default"] = dc
                    for c in m["children"].values():
                        c["tags"] = sorted(set(c.get("tags", []) + m.get("tags", [])))
                    supported[mode] = m

            # Add supported modes
            base["rgb"]["handheld"]["children"]["mode"]["modes"] = supported

            # Set a sane default mode
            for default in ("solid", "pulse", "disabled"):
                if default in supported:
                    base["rgb"]["handheld"]["children"]["mode"]["default"] = default
                    break
            else:
                # fallback to any supported mode to have persistence in the mode
                base["rgb"]["handheld"]["children"]["mode"]["default"] = next(
                    iter(supported)
                )
        return base

    def update(self, conf: Config):
        cap = self.emit.get_capabilities()

        if DEBUG_MODE:
            cap = {
                "_dbg": {
                    "rgb": {
                        "controller": False,
                        "modes": {
                            "disabled": [],
                            "solid": ["color"],
                            "pulse": ["color", "speed", "speedd"],
                            "duality": ["dual", "speedd"],
                            "rainbow": ["brightness", "speed", "speedd"],
                            "spiral": ["brightness", "speed", "speedd", "direction"],
                        },
                    }
                }
            }

        if not cap:
            if self.modes:
                self.modes = None
                self.emit({"type": "settings"})
            return

        # Check controller id and force setting the leds if it changed.
        # This will reset the led color after suspend or after exitting
        # dualsense emulation.
        uniq = next(iter(cap))
        ccap = cap[uniq]
        if uniq != self.uniq:
            self.prev = None
            self.uniq = uniq

        rgb = ccap["rgb"]
        refresh_settings = False
        if rgb:
            # Refresh on initial load
            if not self.modes:
                refresh_settings = True

            # Refresh if controller takes control of the LEDs
            new_controller = rgb["controller"]
            if self.controller != new_controller:
                refresh_settings = True

            self.controller = new_controller
            self.modes = rgb["modes"]

        if self.loaded:
            new_enabled = conf["hhd"]["settings"]["rgb"].to(bool)
            if new_enabled != self.enabled:
                refresh_settings = True
                self.enabled = new_enabled

        if refresh_settings:
            self.init_count = 0
            self.init_last = 0
            self.emit({"type": "settings"})
            return

        # All checks were ran and settings were updated
        # if the controller has control of the LEDs
        # or they are not enabled, exit.
        if not self.enabled or self.controller:
            return

        curr = time.perf_counter()
        init = False

        rgb_conf = conf["rgb"]["handheld"]["mode"]
        if self.prev and self.prev != rgb_conf:
            self.init = False
        elif self.init:
            # Initialize by setting the LEDs X times
            # to avoid early boot having it not set
            if self.init_count >= RGB_SET_TIMES:
                self.init = False
                return

            # Wait inbetween setting the LEDS
            curr = time.perf_counter()
            if curr - self.init_last < RGB_SET_INTERVAL:
                return

            self.init_count += 1
            self.init_last = curr
            logger.info(
                f"Initializing RGB (repeat {self.init_count}/{RGB_SET_TIMES}, interval: {RGB_SET_INTERVAL})"
            )
            init = True
        elif self.queue_leds and self.queue_leds < curr:
            # Set the LEDs after two seconds with init
            logger.info("Running full rgb command.")
            init = True
        elif self.prev and self.prev == rgb_conf:
            return

        self.prev = rgb_conf.copy()

        # Get event info
        mode = rgb_conf["mode"].to(str)
        if mode in rgb_conf:
            info = cast(dict, rgb_conf[mode].conf)
        else:
            info = {}
        ev: Event | None = None
        if not self.modes or mode not in self.modes:
            return

        brightness = 1
        brightnessd = "high"
        speedd = "high"
        direction = "left"
        speed = 1
        red = 0
        green = 0
        blue = 0
        red2 = 0
        green2 = 0
        blue2 = 0
        color2_set = False
        always_init = True
        oxp = None

        log = f"Setting RGB to mode '{mode}'"
        for cap in self.modes[cast(RgbMode, mode)]:
            match cap:
                case "color":
                    red, green, blue = hsb_to_rgb(
                        info["hue"],
                        info["saturation"],
                        info["brightness"],
                    )
                    # Cannot init leds with color slider because it is too fast
                    always_init = False
                    log += f" with color: {red:3d}, {green:3d}, {blue:3d}"
                case "dual":
                    red, green, blue = hsb_to_rgb(
                        info["hue"],
                        info["saturation"],
                        info["brightness"],
                    )
                    color2_set = True
                    red2, green2, blue2 = hsb_to_rgb(
                        info["hue2"],
                        info["saturation"],
                        info["brightness"],
                    )
                    # Cannot init leds with color slider because it is too fast
                    always_init = False
                    log += f" with colors: {red:3d}, {green:3d}, {blue:3d} and {red2:3d}, {green2:3d}, {blue2:3d}"
                case "brightness":
                    log += f", brightness: {info['brightness']}"
                    brightness = info["brightness"] / 100
                case "speed":
                    log += f", speed: {info['speed']}"
                    speed = info["speed"] / 100
                case "brightnessd":
                    log += f", brightness: {info['brightnessd']}"
                    brightnessd = cast(
                        Literal["low", "medium", "high"], info["brightnessd"]
                    )
                case "speedd":
                    log += f", speed: {info['speedd']}"
                    speedd = cast(Literal["low", "medium", "high"], info["speedd"])
                case "direction":
                    log += f", direction: {info['direction']}"
                    direction = cast(Literal["left", "right"], info["direction"])
                case "oxp":
                    brightnessd = cast(
                        Literal["low", "medium", "high"], info["brightnessd"]
                    )
                    log += f", mode: '{info['mode']}', brightness: '{brightnessd}'"
                    oxp = info["mode"]
                case "oxp-secondary":
                    log += f", center hue: {info['hue']}, enabled: {info['secondary']}"
                    if info["secondary"]:
                        red2, green2, blue2 = hsb_to_rgb(
                            info["hue"],
                            100,
                            100,
                        )
                    else:
                        red2 = green2 = blue2 = 0
                    color2_set = True

        log += "."

        if not color2_set:
            red2 = red
            green2 = green
            blue2 = blue

        ev = {
            "type": "led",
            "initialize": init
            or always_init,  # Always initialize, saves problems on the ally
            "code": "main",
            "mode": cast(RgbMode, mode),
            "direction": direction,
            "brightness": brightness,
            "brightnessd": brightnessd,
            "speed": speed,
            "speedd": speedd,
            "red": red,
            "green": green,
            "blue": blue,
            "red2": red2,
            "green2": green2,
            "blue2": blue2,
            "oxp": oxp,
        }
        if not always_init:
            self.queue_leds = curr + RGB_QUEUE_RGB

        # Avoid setting the LEDs too fast.
        if curr - self.last_set < RGB_MIN_INTERVAL and not init:
            return

        logger.info(log)
        self.last_set = curr
        self.last_ev = ev
        self.emit.inject(ev)
        if init:
            self.queue_leds = None


def autodetect(existing: Sequence[HHDPlugin]) -> Sequence[HHDPlugin]:
    if len(existing):
        return existing

    return [RgbPlugin()]
