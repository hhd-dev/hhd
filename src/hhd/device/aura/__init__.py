import logging
import os
import select
import time
from threading import Event, Thread
from typing import Literal, Sequence, TypedDict, cast

from hhd.controller.base import RgbMode
from hhd.controller.lib.hid import Device as HIDDevice
from hhd.controller.lib.hid import enumerate_unique
from hhd.i18n import _
from hhd.plugins import (
    Config,
    Context,
    Emitter,
    HHDPlugin,
    get_outputs_config,
    load_relative_yaml,
)
from hhd.plugins.settings import HHDSettings
from hhd.utils import get_distro_color, hsb_to_rgb

logger = logging.getLogger(__name__)

SEARCH_INTERVAL = 10

AURA_CONFIGS_LIGHTBAR = {
    "solid": ["color"],
    "pulse": ["color", "speedd"],
    "duality": ["dual", "speedd"],
    "cycle": ["speedd", "direction"],
    "rainbow": ["speedd"],
    "strobe": ["color", "speedd"],
}

AURA_CONFIGS_USB = {
    "solid": ["color"],
    "pulse": ["color", "speedd"],
    "duality": ["dual", "speedd"],
    # "cycle": ["speedd", "direction"],
    "rainbow": ["speedd"],
    "strobe": ["color", "speedd"],
}

ASUS_VID = 0x0B05
BRIGHTNESS_MAP = ["disabled", "low", "medium", "high"]
AURA_APPLICATIONS = [0xFF310076, 0xFF310079, 0xFF310080]

AURA_CONFIGS = {
    # Z13 Lightbar
    0x18C6: (_("Lightbar"), AURA_CONFIGS_LIGHTBAR),
    # ROG Keyboards (Z13 incl.)
    0x1A30: (_("Keyboard"), AURA_CONFIGS_USB),
}

AURA_CONFGIS_WMI = {
    "solid": ["color"],
}

WMI_LOCATION = "/sys/class/leds/asus::kbd_backlight/brightness"
WMI_NOTIFICATION = "/sys/class/leds/asus::kbd_backlight/brightness_hw_changed"

RGB_INPUT_ID = 0x5A
RGB_AURA_ID = 0x5D

RGB_HANDSHAKE = lambda key: bytes(
    [
        key,
        0x41,
        0x53,
        0x55,
        0x53,
        0x20,
        0x54,
        0x65,
        0x63,
        0x68,
        0x2E,
        0x49,
        0x6E,
        0x63,
        0x2E,
    ]
)
RGB_INIT_OTHER = lambda key: [
    bytes([key, 0xB9, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]),
    bytes([key, 0x05, 0x20, 0x31, 0, 0x1A]),
]
DYN_RGB_INIT = lambda key: buf([key, 0xC0, 0x03, 0x01])
RGB_APPLY = lambda key: buf([key, 0xB4])
RGB_SET = lambda key: buf([key, 0xB5, 0, 0, 0])
RGB_APPLY_DELAY = 1
RGB_TDP_DELAY = 1.5


def init_rgb_dev(key: int, dev: HIDDevice):
    # Send handshake command
    init_cmd = RGB_HANDSHAKE(key)
    dev.send_feature_report(init_cmd)

    # Device replies with the same start
    rec = dev.get_feature_report(key, 64)
    for a1, a2 in zip(init_cmd, rec):
        assert a1 == a2, f"Init command mismatch:\n" f"{init_cmd.hex()} != {rec.hex()}"

    # Maybe not required
    # # More initialization commands
    # for cmd in RGB_INIT_OTHER(key):
    #     dev.send_feature_report(cmd)


class AuraDevice(TypedDict):
    vid: int
    pid: int
    application: int
    fn: str
    name: str
    cfg_name: str
    init: bool
    disabled: bool
    modes: dict[str, list[str]]
    dev: HIDDevice
    last_mode: RgbMode | None


def buf(x):
    return bytes(x) + bytes(64 - len(x))


def monitor_brightness(emit, should_exit: Event):
    if not os.path.exists(WMI_NOTIFICATION):
        logger.warning("WMI notification file does not exist: %s", WMI_NOTIFICATION)
        return

    with open(WMI_NOTIFICATION, "r") as f:
        p = select.poll()
        p.register(f.fileno(), select.POLLPRI)
        while not should_exit.is_set():
            # Use a time limit for exit to be possible
            v = p.poll(2000)
            if not v:
                continue
            try:
                f.read()
                f.seek(0)
            except OSError as e:
                if e.errno == 61:
                    continue
                raise
            emit({"type": "special", "event": "brightness_changed"})


def get_aura_devices(
    existing: dict[str, AuraDevice] = {},
) -> tuple[dict[str, AuraDevice], bool]:
    out = {}

    found = set()
    for d in enumerate_unique(vid=ASUS_VID):
        application = d.get("usage_page", 0x0000) << 16 | d.get("usage", 0x0000)
        if d["path"] in existing:
            ref = existing[d["path"]]
            if (
                d["vendor_id"] != ref["vid"]
                or d["product_id"] != ref["pid"]
                or application != ref["application"]
            ):
                # Device changed, do not add it to found
                continue
            # Skip already known devices
            found.add(d["path"])
            continue
        if application not in AURA_APPLICATIONS:
            continue
        if d["product_id"] not in AURA_CONFIGS:
            continue

        name, modes = AURA_CONFIGS[d["product_id"]]
        cfg_name = f"{d['vendor_id']:04x}_{d['product_id']:04x}"

        try:
            dev = HIDDevice(path=d["path"])
        except Exception as e:
            logger.warning(
                "Failed to open Aura device %s (%04x:%04x): %s",
                d["path"],
                d["vendor_id"],
                d["product_id"],
                e,
            )
            continue

        out[d["path"]] = AuraDevice(
            name=name,
            cfg_name=cfg_name,
            vid=d["vendor_id"],
            pid=d["product_id"],
            application=application,
            fn=d["path"],
            init=True,
            disabled=False,
            modes=modes,
            dev=dev,
            last_mode=None,
        )
        logger.info(
            "Found Aura device %s (%s, %04x:%04x) with modes:\n%s",
            name,
            d["path"].decode("utf-8"),
            d["vendor_id"],
            d["product_id"],
            list(modes),
        )

    updated = False
    for k in list(existing.keys()):
        if k not in found:
            logger.info(
                "Removing Aura device %s (%s, %04x:%04x) from known devices",
                existing[k]["fn"],
                existing[k]["name"],
                existing[k]["vid"],
                existing[k]["pid"],
            )
            del existing[k]
            updated = True

    updated |= bool(out)
    return (
        dict(sorted({**existing, **out}.items(), key=lambda x: x[1]["cfg_name"])),
        updated,
    )


def rgb_command(
    mode: RgbMode,
    direction,
    speed: str,
    red: int,
    green: int,
    blue: int,
    o_red: int,
    o_green: int,
    o_blue: int,
):
    c_direction = 0x00
    set_speed = True

    match mode:
        case "solid":
            # Static
            c_mode = 0x00
            set_speed = False
        case "pulse":
            # Strobing
            # c_mode = 0x0A
            # Spiral is agressive
            # Use breathing instead
            # Breathing
            c_mode = 0x01
            o_red = 0
            o_green = 0
            o_blue = 0
        case "strobe":
            # Strobing
            c_mode = 0x0A
        case "rainbow":
            # Color cycle
            c_mode = 0x02
        case "spiral" | "cycle":
            # Rainbow
            c_mode = 0x03
            red = 0
            green = 0
            blue = 0
            if direction == "left":
                c_direction = 0x01
        case "duality":
            # Breathing
            c_mode = 0x01
        # case "direct":
        #     # Direct/Aura
        #     c_mode = 0xFF
        # Should be used for dualsense emulation/ambilight stuffs
        case _:
            c_mode = 0x00

    c_speed = 0xE1
    if set_speed:
        match speed:
            case "low":
                c_speed = 0xE1
            case "medium":
                c_speed = 0xEB
            case _:  # "high"
                c_speed = 0xF5

    c_zone = 0x00
    return buf(
        [
            RGB_AURA_ID,
            0xB3,
            c_zone,  # zone
            c_mode,  # mode
            red,
            green,
            blue,
            c_speed if mode != "solid" else 0x00,
            c_direction,
            0x00,  # breathing
            o_red,  # these only affect the breathing mode
            o_green,
            o_blue,
            0,
            0,
            0,
            0,
        ]
    )


def get_aura_mode_cmd(cfg, dev: AuraDevice):
    # Get event info
    mode = cfg["mode"].to(str)
    if mode in cfg:
        info = cast(dict, cfg[mode].conf)
    else:
        info = {}
    if not dev["modes"] or mode not in dev["modes"]:
        return None, mode, False

    red = green = blue = red2 = green2 = blue2 = 0
    speedd = "medium"
    direction = "left"
    color2_set = False
    log = f"Setting Aura {dev['name']} ({dev['vid']:04x}:{dev['pid']:04x}) to mode '{mode}'"
    always_init = True
    for cap in dev["modes"][mode]:
        match cap:
            case "color":
                red, green, blue = hsb_to_rgb(
                    info["hue"],
                    info["saturation"],
                    100,
                )
                log += f" with color: {red:3d}, {green:3d}, {blue:3d}"
                always_init = False
            case "dual":
                red, green, blue = hsb_to_rgb(
                    info["hue"],
                    info["saturation"],
                    100,
                )
                red2, green2, blue2 = hsb_to_rgb(
                    info["hue2"],
                    info["saturation"],
                    100,
                )
                color2_set = True
                log += f" with colors: {red:3d}, {green:3d}, {blue:3d} and {red2:3d}, {green2:3d}, {blue2:3d}"
                always_init = False
            case "speedd":
                log += f", speed: {info['speedd']}"
                speedd = cast(Literal["low", "medium", "high"], info["speedd"])
            case "direction":
                log += f", direction: {info['direction']}"
                direction = cast(Literal["left", "right"], info["direction"])

    # logger.info(log)
    return (
        rgb_command(
            mode,
            direction,
            speedd,
            red,
            green,
            blue,
            red2 if color2_set else 0,
            green2 if color2_set else 0,
            blue2 if color2_set else 0,
        ),
        mode,
        always_init,
    )


def set_aura_brightness(
    brightness: str, devices: dict[str, AuraDevice], has_wmi: bool = False
) -> bool:
    if not devices:
        return False

    match brightness:
        case "high":
            c = 0x03
        case "medium":
            c = 0x02
        case "low":
            c = 0x01
        case _:
            c = 0x00

    if os.path.exists(WMI_LOCATION) and has_wmi:
        try:
            with open(WMI_LOCATION, "w") as f:
                f.write(str(c))
            logger.info("Set Aura brightness to %s", brightness)
            return False
        except Exception as e:
            logger.error("Failed to set WMI brightness: %s", e)
            return False

    error = False
    for dev in devices.values():
        if dev["disabled"]:
            continue
        try:
            # Set brightness on the device
            dev["dev"].send_feature_report(buf([RGB_INPUT_ID, 0xBA, 0xC5, 0xC4, c]))
        except Exception as e:
            logger.error(
                "Failed to set brightness for Aura device %s (%04x:%04x): %s",
                dev["fn"],
                dev["vid"],
                dev["pid"],
                e,
            )
            dev["disabled"] = True
            try:
                dev["dev"].close()
            except Exception:
                pass
            error = True
    return error


def get_aura_power_cmd(power) -> bytes:
    boot = power.get("boot", False)
    awake = power.get("awake", False)
    sleep = power.get("sleep", False)
    shutdown = power.get("shutdown", False)

    keyb = 0
    bar = 0
    lid_rear = 0

    if boot:
        keyb |= (1 << 0) | (1 << 1)
        bar |= 1 << 1
        lid_rear |= (1 << 0) | (1 << 4)

    if awake:
        keyb |= (1 << 2) | (1 << 3)
        bar |= (1 << 0) | (1 << 2)
        lid_rear |= (1 << 1) | (1 << 5)

    if sleep:
        keyb |= (1 << 4) | (1 << 5)
        bar |= 1 << 3
        lid_rear |= (1 << 2) | (1 << 6)

    if shutdown:
        keyb |= (1 << 6) | (1 << 7)
        bar |= 1 << 4
        lid_rear |= (1 << 3) | (1 << 7)

    return bytes(
        [
            RGB_AURA_ID,
            0xBD,
            0x01,
            keyb,
            bar,
            lid_rear,
            lid_rear,
            0xFF,
        ]
    )


def set_aura_power(power, devs) -> bool:
    error = False
    cmd = get_aura_power_cmd(power)

    for dev in devs.values():
        if dev["disabled"]:
            continue
        try:
            # Set brightness on the device
            dev["dev"].send_feature_report(cmd)
        except Exception as e:
            logger.error(
                "Failed to set brightness for Aura device %s (%04x:%04x): %s",
                dev["fn"],
                dev["vid"],
                dev["pid"],
                e,
            )
            dev["disabled"] = True
            try:
                dev["dev"].close()
            except Exception:
                pass
            error = True
    return error


class AuraPlugin(HHDPlugin):
    name = "aura_rgb_controller"
    priority = 18
    log = "aura"

    def open(
        self,
        emit: Emitter,
        context: Context,
    ):
        self.emit = emit
        self.queue_apply = {}
        self.tdp_changes = False
        self.context = context
        self.enabled = False
        self.loaded_devices = set()
        self.devices = {}
        self.prev_cfg = None
        self.has_wmi = os.path.exists(WMI_LOCATION)
        self.init_brightness = not self.has_wmi

        # Set a sane default color
        self.dc = get_distro_color()

        self.t = None
        self.should_exit = Event()

    def settings(self) -> HHDSettings:
        # If RGB support is disabled
        # return enable option only
        base = load_relative_yaml("settings.yml")
        self.loaded_devices = set()
        if not self.enabled:
            del base["rgb"]
            return base

        if not self.devices:
            return {}

        modes = load_relative_yaml("../../plugins/rgb/modes.yml")
        capabilities = load_relative_yaml("../../plugins/rgb/capabilities.yml")

        cfgs = {}
        for d in self.devices.values():
            if d["disabled"]:
                continue
            supported = {}
            for mode, caps in d["modes"].items():
                if mode in modes:
                    m = modes[mode]
                    m["children"] = {}
                    for cap in caps:
                        # We use four step brightness for the keyboard button to work
                        m["children"].update(
                            {
                                k: dict(v)
                                for k, v in capabilities[cap].items()
                                if k != "brightness"
                            }
                        )
                        if cap == "color":
                            m["children"]["hue"]["default"] = self.dc
                    for c in m["children"].values():
                        c["tags"] = sorted(set(c.get("tags", []) + m.get("tags", [])))
                    supported[mode] = m

            # Add supported modes
            cfg = {
                "type": "mode",
                "title": d["name"],
                "modes": supported,
            }

            # Set a sane default mode
            for default in ("solid", "pulse"):
                if default in supported:
                    cfg["default"] = default
                    break
            else:
                # fallback to any supported mode to have persistence in the mode
                cfg["default"] = next(iter(supported))

            cfgs[d["cfg_name"]] = cfg
            self.loaded_devices.add(d["cfg_name"])

        base_settings = base["rgb"]["aura"]["children"]
        base["rgb"]["aura"]["children"] = {
            "brightness": base_settings["brightness"],
            **cfgs,
            "power": base_settings["power"],
        }

        if self.has_wmi:
            # If the driver is loaded, we will get the brightness from the os
            del base["rgb"]["aura"]["children"]["brightness"]["default"]

        return base

    def update(self, conf: Config):
        enabled_prev = self.enabled
        self.enabled = conf.get("hhd.settings.aura", False)

        if enabled_prev != self.enabled:
            self.emit({"type": "settings"})

        if not self.enabled:
            return

        curr_t = time.perf_counter()
        error = False
        if self.prev_cfg is not None and "rgb.aura" in conf:
            curr = conf["rgb.aura"]
            power_settings = curr.get("power", None)
            if power_settings is not None:
                self.tdp_changes = power_settings.get("tdp_changes", False)

            # Set per device settings
            for d in self.devices.values():
                k = d["cfg_name"]
                if k not in self.loaded_devices:
                    continue
                if d["disabled"]:
                    continue
                if k not in curr:
                    continue

                data = curr[k]
                init = d["init"]
                queued = k in self.queue_apply and self.queue_apply[k] < curr_t
                if queued:
                    del self.queue_apply[k]
                if (
                    k in self.prev_cfg
                    and data == self.prev_cfg[k]
                    and not init
                    and not queued
                ):
                    continue
                d["init"] = False

                cmd, new_mode, always_init = get_aura_mode_cmd(data, d)
                if cmd is None:
                    continue
                chanded_mode = new_mode != d["last_mode"]

                try:
                    if init:
                        init_rgb_dev(RGB_AURA_ID, d["dev"])
                        if power_settings is not None:
                            # Set power settings on init
                            d["dev"].send_feature_report(
                                get_aura_power_cmd(power_settings),
                            )

                        # Needs time to initialize, get it next cycle
                        self.queue_apply[k] = curr_t + RGB_APPLY_DELAY
                    else:
                        d["dev"].send_feature_report(cmd)
                        d["last_mode"] = new_mode

                        if chanded_mode or queued or always_init or init:
                            d["dev"].send_feature_report(RGB_SET(RGB_AURA_ID))
                            d["dev"].send_feature_report(RGB_APPLY(RGB_AURA_ID))
                        else:
                            self.queue_apply[k] = curr_t + RGB_APPLY_DELAY

                except Exception as e:
                    logger.error(
                        f"Failed to set mode to {d['name']} ({d['fn']}, {d['vid']:04x}_{d['pid']:04x}), removing:\n{e}",
                    )
                    d["disabled"] = True
                    try:
                        d["dev"].close()
                    except Exception:
                        pass
                    error = True
                    continue

            # Set common settings (allow to init)
            brightness = curr.get("brightness", None)
            if brightness is not None and (
                brightness != self.prev_cfg.get("brightness", None)
                or self.init_brightness
            ):
                error |= set_aura_brightness(brightness, self.devices, self.has_wmi)
                self.init_brightness = False

            if (
                power_settings is not None
                and self.prev_cfg.get("power", None)
                and (power_settings != self.prev_cfg.get("power", None))
            ):
                error |= set_aura_power(power_settings, self.devices)

        self.devices, updated = get_aura_devices(self.devices)
        if updated:
            logger.info("Found %d Aura devices", len(self.devices))
            self.emit({"type": "settings"})
        if error:
            self.emit({"type": "settings"})

        if self.has_wmi:
            if self.t is None:
                self.should_exit.clear()
                self.t = Thread(
                    target=monitor_brightness,
                    args=(self.emit, self.should_exit),
                    name="Aura WMI brightness monitor",
                )
                self.t.start()

            with open(WMI_LOCATION, "r") as f:
                brightness = int(f.read().strip())
            br_str = BRIGHTNESS_MAP[min(3, brightness)]
            conf["rgb.aura.brightness"] = br_str
        
        if self.loaded_devices and "rgb.aura" in conf:
            self.prev_cfg = conf["rgb.aura"]

    def close(self):
        if self.t is not None:
            self.should_exit.set()
            self.t.join()
            self.t = None

        for d in self.devices.values():
            try:
                d["dev"].close()
            except Exception as e:
                logger.warning(
                    "Failed to close Aura device %s (%04x:%04x): %s",
                    d["fn"],
                    d["vid"],
                    d["pid"],
                    e,
                )

        self.devices = {}

    def notify(self, events):
        if not self.tdp_changes:
            return

        color = None
        for ev in events:
            if ev["type"] == "special":
                match ev["event"]:
                    case "tdp_cycle_quiet":
                        color = (0, 0, 255)
                    case "tdp_cycle_balanced":
                        color = (255, 255, 255)
                    case "tdp_cycle_performance":
                        color = (255, 0, 0)
                    case "tdp_cycle_custom":
                        color = (157, 0, 255)
                    # case "wakeup":
                    #     for d in self.devices.values():
                    #         if d["disabled"]:
                    #             continue
                    #         d['init'] = True
                    case _:
                        color = None

        if color is None:
            return

        error = False
        for d in self.devices.values():
            if d["disabled"]:
                continue
            try:
                cmd = rgb_command(
                    "solid",
                    "left",
                    "medium",
                    *color,
                    0,  # o_red
                    0,  # o_green
                    0,  # o_blue
                )
                d["dev"].send_feature_report(cmd)
                d["dev"].send_feature_report(RGB_SET(RGB_AURA_ID))
                self.queue_apply[d["cfg_name"]] = (
                    time.perf_counter() + RGB_TDP_DELAY
                )
            except Exception as e:
                logger.error(
                    f"Failed to set TDP cycle color on {d['name']} ({d['vid']:04x}:{d['pid']:04x}): {e}",
                )
                d["disabled"] = True
                error = True
                try:
                    d["dev"].close()
                except Exception:
                    pass

        if error:
            self.emit({"type": "settings"})

def autodetect(existing: Sequence[HHDPlugin]) -> Sequence[HHDPlugin]:
    if len(existing):
        return existing

    # Match just product name
    # if a device exists here its officially supported
    with open("/sys/devices/virtual/dmi/id/sys_vendor") as f:
        vendor = f.read().strip()

    # Match just product number, should be enough for now
    with open("/sys/devices/virtual/dmi/id/product_name") as f:
        # Different variants of the ally can have an additional _RC71L or not
        dmi = f.read().strip()

    if vendor == "ASUSTeK COMPUTER INC." and "ROG Ally" not in dmi:
        return [AuraPlugin()]

    return []
