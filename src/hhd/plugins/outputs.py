from typing import Any, Mapping, Sequence

from .utils import load_relative_yaml
from ..controller.base import Consumer, Producer
from ..controller.virtual.dualsense import Dualsense, TouchpadCorrectionType
from ..controller.virtual.uinput import (
    HHD_PID_MOTION,
    HHD_PID_TOUCHPAD,
    MOTION_AXIS_MAP,
    MOTION_CAPABILITIES,
    TOUCHPAD_AXIS_MAP,
    TOUCHPAD_BUTTON_MAP,
    TOUCHPAD_CAPABILITIES,
    UInputDevice,
)


def get_outputs(
    conf, touch_conf, motion: bool = False
) -> tuple[Sequence[Producer], Sequence[Consumer], Mapping[str, Any]]:
    producers = []
    consumers = []

    controller = conf["mode"].to(str)
    if touch_conf is not None:
        touchpad = touch_conf["mode"].to(str)
        correction = touch_conf["controller.correction"].to(TouchpadCorrectionType)
    else:
        touchpad = "controller"
        correction = "stretch"

    uses_touch = False
    uses_leds = False
    match controller:
        case "dualsense":
            uses_touch = touchpad == "controller"
            uses_leds = conf["dualsense.led_support"].to(bool)
            d = Dualsense(
                touchpad_method=correction,
                edge_mode=conf["dualsense.edge_mode"].to(bool),
                use_bluetooth=conf["dualsense.bluetooth_mode"].to(bool),
                enable_touchpad=uses_touch,
                enable_rgb=uses_leds,
                fake_timestamps=not motion,
            )
            producers.append(d)
            consumers.append(d)
        case "uinput":
            d = UInputDevice(phys="phys-hhd-main")
            producers.append(d)
            consumers.append(d)
            if motion:
                d = UInputDevice(
                    name="Handheld Daemon Controller Motion Sensors",
                    phys="phys-hhd-main",
                    capabilities=MOTION_CAPABILITIES,
                    pid=HHD_PID_MOTION,
                    btn_map={},
                    axis_map=MOTION_AXIS_MAP,
                    output_imu_timestamps=True,
                )
                producers.append(d)
                consumers.append(d)
        case _:
            raise RuntimeError(f"Invalid controller type: '{controller}'.")

    if touchpad == "emulation":
        d = UInputDevice(
            name="Handheld Daemon Touchpad",
            phys="phys-hhd-main",
            capabilities=TOUCHPAD_CAPABILITIES,
            pid=HHD_PID_TOUCHPAD,
            btn_map=TOUCHPAD_BUTTON_MAP,
            axis_map=TOUCHPAD_AXIS_MAP,
            output_timestamps=True,
        )
        producers.append(d)
        consumers.append(d)
        uses_touch = True

    return (
        producers,
        consumers,
        {"uses_touch": uses_touch, "uses_leds": uses_leds, "is_dual": False},
    )


def get_outputs_config():
    return load_relative_yaml("outputs.yml")
