import logging
from typing import Any, Mapping, Sequence

from ..controller.base import Consumer, Producer, RgbMode, RgbZones
from ..controller.virtual.dualsense import Dualsense, TouchpadCorrectionType
from ..controller.virtual.uinput import (
    HHD_PID_MOTION,
    HHD_VID,
    HHD_PID_TOUCHPAD,
    MOTION_AXIS_MAP,
    MOTION_AXIS_MAP_FLIP_Z,
    MOTION_CAPABILITIES,
    MOTION_INPUT_PROPS,
    TOUCHPAD_AXIS_MAP,
    TOUCHPAD_BUTTON_MAP,
    TOUCHPAD_CAPABILITIES,
    CONTROLLER_THEMES,
    MOTION_LEFT_AXIS_MAP,
    MOTION_LEFT_AXIS_MAP_FLIP_Z,
    XBOX_ELITE_BUTTON_MAP,
    GAMEPAD_BUTTON_MAP,
    UInputDevice,
)
from .plugin import is_steam_gamepad_running
from .utils import load_relative_yaml

logger = logging.getLogger(__name__)


def get_outputs(
    conf,
    touch_conf,
    motion: bool = False,
    *,
    controller_id: int = 0,
    emit=None,
    dual_motion: bool = False,
    rgb_modes: Sequence[RgbMode] | None = None,
    rgb_zones: RgbZones = "mono",
) -> tuple[Sequence[Producer], Sequence[Consumer], Mapping[str, Any]]:
    producers = []
    consumers = []
    nintendo_qam = False

    controller = conf["mode"].to(str)
    desktop_disable = False
    if touch_conf is not None:
        touchpad = touch_conf["mode"].to(str)
        correction = touch_conf["controller.correction"].to(TouchpadCorrectionType)
        if touchpad in ("emulation", "controller"):
            desktop_disable = touch_conf[touchpad]["desktop_disable"].to(bool)
    else:
        touchpad = "controller"
        correction = "stretch"

    # Run steam check for touchpad
    steam_check = (
        is_steam_gamepad_running(emit.ctx) if emit and desktop_disable else None
    )
    match steam_check:
        case True:
            logger.info("Gamepadui active. Activating touchpad emulation.")
        case False:
            logger.info("Gamepadui closed. Disabling touchpad emulation.")

    uses_touch = False
    uses_leds = False
    noob_mode = False
    flip_z = False
    match controller:
        case "dualsense_edge":
            UInputDevice.close_cached()
            flip_z = conf["dualsense_edge.flip_z"].to(bool)
            uses_touch = touchpad == "controller" and steam_check is not False
            uses_leds = conf.get("dualsense_edge.led_support", False)
            d = Dualsense(
                touchpad_method=correction,
                edge_mode=True,
                use_bluetooth=conf["dualsense_edge.bluetooth_mode"].to(bool),
                enable_touchpad=uses_touch,
                enable_rgb=uses_leds,
                fake_timestamps=not motion,
                sync_gyro=conf["dualsense_edge.sync_gyro"].to(bool) and motion,
                paddles_to_clicks=False,
                flip_z=flip_z,
                controller_id=controller_id,
                cache=True,
            )
            producers.append(d)
            consumers.append(d)
        case "dualsense":
            UInputDevice.close_cached()
            flip_z = conf["dualsense.flip_z"].to(bool)
            uses_touch = touchpad == "controller" and steam_check is not False
            uses_leds = conf.get("dualsense.led_support", False)
            d = Dualsense(
                touchpad_method=correction,
                edge_mode=False,
                use_bluetooth=conf["dualsense.bluetooth_mode"].to(bool),
                enable_touchpad=uses_touch,
                enable_rgb=uses_leds,
                fake_timestamps=not motion,
                sync_gyro=conf["dualsense.sync_gyro"].to(bool) and motion,
                paddles_to_clicks=conf["dualsense.paddles_to_clicks"].to(bool),
                flip_z=flip_z,
                controller_id=controller_id,
                cache=True,
            )
            producers.append(d)
            consumers.append(d)
        case "uinput" | "xbox_elite" | "joycon_pair":
            Dualsense.close_cached()
            version = 1
            if controller == "joycon_pair":
                theme = "joycon_pair"
                nintendo_qam = conf["joycon_pair.nintendo_qam"].to(bool)
                button_map = GAMEPAD_BUTTON_MAP
                bus = 0x06
                version = 0
            elif controller == "xbox_elite":
                theme = "xbox_one_elite"
                button_map = XBOX_ELITE_BUTTON_MAP
                bus = 0x03
            else:
                noob_mode = conf.get("uinput.noob_mode", False)
                # theme = conf.get("uinput.theme", "hhd")
                theme = 'hhd'
                nintendo_qam = conf["uinput.nintendo_qam"].to(bool)
                # flip_z = conf["uinput.flip_z"].to(bool)
                flip_z = False
                button_map = GAMEPAD_BUTTON_MAP
                bus = 0x03 if theme == "hhd" else 0x06
            vid, pid, name = CONTROLLER_THEMES[theme]
            addr = "phys-hhd-main"
            if controller_id:
                addr = f"phys-hhd-{controller_id:02d}"
            d = UInputDevice(
                name=name,
                vid=vid,
                pid=pid,
                phys=addr,
                uniq=addr,
                btn_map=button_map,
                bus=bus,
                version=version,
                cache=True,
            )
            producers.append(d)
            consumers.append(d)
            # Deactivate motion if using an xbox theme
            motion = (theme != "hhd" and "xbox" not in theme) and motion
            if motion:
                d = UInputDevice(
                    name=f"{name} Motion Sensors",
                    vid=vid,
                    pid=pid,
                    phys=addr,
                    uniq=addr,
                    bus=bus,
                    version=version,
                    capabilities=MOTION_CAPABILITIES,
                    btn_map={},
                    axis_map=(MOTION_AXIS_MAP_FLIP_Z if flip_z else MOTION_AXIS_MAP),
                    output_imu_timestamps=True,
                    input_props=MOTION_INPUT_PROPS,
                    ignore_cmds=True,
                    cache=True,
                    motions_device=True,
                )
                producers.append(d)
                consumers.append(d)
        case _:
            raise RuntimeError(f"Invalid controller type: '{controller}'.")

    dual_motion = motion and dual_motion
    if dual_motion:
        d = Dualsense(
            edge_mode=False,
            use_bluetooth=True,
            enable_touchpad=False,
            enable_rgb=False,
            fake_timestamps=False,
            sync_gyro=True,
            paddles_to_clicks=False,
            flip_z=flip_z,
            controller_id=5,
            cache=True,
            left_motion=True,
        )
        producers.append(d)
        consumers.append(d)

    if touchpad == "emulation" and steam_check is not False:
        d = UInputDevice(
            name="Handheld Daemon Touchpad",
            phys="phys-hhd-main",
            capabilities=TOUCHPAD_CAPABILITIES,
            pid=HHD_PID_TOUCHPAD,
            btn_map=TOUCHPAD_BUTTON_MAP,
            axis_map=TOUCHPAD_AXIS_MAP,
            output_timestamps=True,
            ignore_cmds=True,
        )
        producers.append(d)
        consumers.append(d)
        uses_touch = True

    return (
        producers,
        consumers,
        {
            "uses_touch": uses_touch,
            "rgb_used": uses_leds,
            "rgb_modes": rgb_modes,
            "rgb_zones": rgb_zones,
            "is_dual": False,
            "steam_check": steam_check,
            "steam_check_fn": lambda: emit and is_steam_gamepad_running(emit.ctx),
            "nintendo_qam": nintendo_qam,
            "uses_motion": motion,
            "uses_dual_motion": dual_motion,
            "noob_mode": noob_mode,
        },
    )


def get_outputs_config(
    can_disable: bool = False,
    has_leds: bool = True,
    start_disabled: bool = False,
    default_device: str | None = None,
):
    s = load_relative_yaml("outputs.yml")
    if not can_disable:
        del s["modes"]["disabled"]
    if not has_leds:
        del s["modes"]["dualsense"]["children"]["led_support"]
        del s["modes"]["dualsense_edge"]["children"]["led_support"]
    
    # Set xbox as default for now
    s['default'] = 'uinput'
    # if default_device:
    #     s["default"] = default_device
    if start_disabled:
        s["default"] = "disabled"
    return s
