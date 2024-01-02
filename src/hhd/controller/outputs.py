from typing import Any, Mapping, Sequence

from .base import Consumer, Producer
from .virtual.dualsense import DualsenseEdge, TouchpadCorrectionType
from .virtual.uinput import (
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
    touchpad = touch_conf["mode"].to(str)
    uses_touch = False
    match controller:
        case "dualsense":
            uses_touch = touchpad == "controller"
            d = DualsenseEdge(
                touchpad_method=touch_conf["controller.correction"].to(
                    TouchpadCorrectionType
                ),
                enable_touchpad=uses_touch,
                enable_rgb=conf["dualsense.led_support"],
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

    return producers, consumers, {"uses_touch": uses_touch, "is_dual": False}
