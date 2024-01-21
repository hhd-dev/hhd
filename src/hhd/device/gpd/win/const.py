from hhd.controller import Axis, Button, Configuration
from hhd.controller.physical.evdev import B, to_map

GPD_TOUCHPAD_BUTTON_MAP: dict[int, Button] = to_map(
    {
        "touchpad_touch": [B("BTN_TOOL_FINGER")],  # also BTN_TOUCH
        "touchpad_right": [B("BTN_TOOL_DOUBLETAP"), B("BTN_RIGHT")],
        "touchpad_left": [B("BTN_MOUSE")],
    }
)

GPD_TOUCHPAD_AXIS_MAP: dict[int, Axis] = to_map(
    {
        "touchpad_x": [B("ABS_X")],  # also ABS_MT_POSITION_X
        "touchpad_y": [B("ABS_Y")],  # also ABS_MT_POSITION_Y
    }
)
