from collections import defaultdict
from typing import Sequence

from hhd.controller import Axis, Button, Configuration, Consumer, Event, Producer
from hhd.controller.physical.evdev import B, to_map
from hhd.controller.lib.hid import Device

from ...controller.physical.hidraw import AM, BM, CM
from .hid import rgb_enable, rgb_multi_disable, rgb_multi_load_settings

LGO_TOUCHPAD_BUTTON_MAP: dict[int, Button] = to_map(
    {
        "touchpad_touch": [B("BTN_TOOL_FINGER")],  # also BTN_TOUCH
        "touchpad_click": [B("BTN_TOOL_DOUBLETAP")],
    }
)

LGO_TOUCHPAD_AXIS_MAP: dict[int, Axis] = to_map(
    {
        "touchpad_x": [B("ABS_X")],  # also ABS_MT_POSITION_X
        "touchpad_y": [B("ABS_Y")],  # also ABS_MT_POSITION_Y
    }
)

LGO_RAW_INTERFACE_BTN_ESSENTIALS: dict[int | None, dict[Button, BM]] = {
    0x04: {
        # Misc
        "mode": BM((18 << 3)),
        "share": BM((18 << 3) + 1),
        # Back buttons
        "extra_l1": BM((20 << 3)),
        "extra_l2": BM((20 << 3) + 1),
        "extra_r1": BM((20 << 3) + 2),
        "extra_r2": BM((20 << 3) + 5),
        "extra_r3": BM((20 << 3) + 4),
    }
}


LGO_RAW_INTERFACE_BTN_MAP: dict[int | None, dict[Button, BM]] = {
    0x04: {
        # Misc
        "mode": BM((18 << 3)),
        "share": BM((18 << 3) + 1),
        # Sticks
        "ls": BM((18 << 3) + 2),
        "rs": BM((18 << 3) + 3),
        # D-PAD
        "dpad_up": BM((18 << 3) + 4),
        "dpad_down": BM((18 << 3) + 5),
        "dpad_left": BM((18 << 3) + 6),
        "dpad_right": BM((18 << 3) + 7),
        # Thumbpad
        "a": BM((19 << 3) + 0),
        "b": BM((19 << 3) + 1),
        "x": BM((19 << 3) + 2),
        "y": BM((19 << 3) + 3),
        # Bumpers
        "lb": BM((19 << 3) + 4),
        "lt": BM((19 << 3) + 5),
        "rb": BM((19 << 3) + 6),
        "rt": BM((19 << 3) + 7),
        # Back buttons
        "extra_l1": BM((20 << 3)),
        "extra_l2": BM((20 << 3) + 1),
        "extra_r1": BM((20 << 3) + 2),
        "extra_r2": BM((20 << 3) + 5),
        "extra_r3": BM((20 << 3) + 4),
        # Select
        "start": BM((20 << 3) + 7),
        "select": BM((20 << 3) + 6),
        # Mouse
        "btn_middle": BM((21 << 3)),
    }
}


LGO_RAW_INTERFACE_AXIS_MAP: dict[int | None, dict[Axis, AM]] = {
    0x04: {
        "ls_x": AM(14 << 3, "m8"),
        "ls_y": AM(15 << 3, "m8"),
        "rs_x": AM(16 << 3, "m8"),
        "rs_y": AM(17 << 3, "m8"),
        "lt": AM(22 << 3, "u8"),
        "rt": AM(23 << 3, "u8"),
        # "mouse_wheel": AM(25 << 3, "m8", scale=1), # TODO: Fix weird behavior
        "touchpad_x": AM(26 << 3, "u16"),
        "touchpad_y": AM(28 << 3, "u16"),
        "left_gyro_x": AM(30 << 3, "m8"),
        "left_gyro_y": AM(31 << 3, "m8"),
        "right_gyro_x": AM(32 << 3, "m8"),
        "right_gyro_y": AM(33 << 3, "m8"),
    }
}

LGO_RAW_INTERFACE_CONFIG_MAP: dict[int | None, dict[Configuration, CM]] = {
    0x04: {
        "battery_left": CM(5 << 3, "u8", scale=1, bounds=(0, 100)),
        "battery_right": CM(7 << 3, "u8", scale=1, bounds=(0, 100)),
        "is_connected_left": CM((10 << 3) + 7, "bit"),
        "is_connected_right": CM((11 << 3) + 7, "bit"),
        "is_attached_left": CM((12 << 3) + 7, "bit", flipped=True),
        "is_attached_right": CM((13 << 3) + 7, "bit", flipped=True),
    }
}


class SelectivePasshtrough(Producer, Consumer):
    def __init__(
        self,
        parent,
        forward_buttons: Sequence[Button] = ("share", "mode"),
        passthrough: Sequence[Button] = list(LGO_RAW_INTERFACE_BTN_ESSENTIALS[0x04]),
    ):
        self.parent = parent
        self.state = False

        self.forward_buttons = forward_buttons
        self.passthrough = passthrough

        self.to_disable = []

    def open(self) -> Sequence[int]:
        return self.parent.open()

    def close(self, exit: bool) -> bool:
        return super().close(exit)

    def produce(self, fds: Sequence[int]) -> Sequence[Event]:
        evs: Sequence[Event] = self.parent.produce(fds)

        out = []
        prev_state = self.state
        for ev in evs:
            if ev["type"] == "button" and ev["code"] in self.forward_buttons:
                self.state = ev.get("value", False)

            if ev["type"] == "configuration":
                out.append(ev)
            elif ev["type"] == "button" and ev["code"] in self.passthrough:
                out.append(ev)
            elif ev["type"] == "button" and ev.get("value", False):
                self.to_disable.append(ev["code"])

        if self.state:
            # If mode is pressed, forward all events
            return evs
        elif prev_state:
            # If prev_state, meaning the user released the mode or share button
            # turn off all buttons that were pressed during it
            for btn in self.to_disable:
                out.append({"type": "button", "code": btn, "value": False})
            self.to_disable = []
            return out
        else:
            # Otherwise, just return the standard buttons
            return out

    def consume(self, events: Sequence[Event]):
        return self.parent.consume(events)


def rgb_callback(dev: Device, events: Sequence[Event]):
    for ev in events:
        if ev["type"] == "led":
            if ev["mode"] == "disable":
                reps = rgb_multi_disable()
            else:
                match ev["mode"]:
                    case "blinking":
                        mode = "pulse"
                    case "rainbow":
                        mode = "dynamic"
                    case "solid":
                        mode = "solid"
                    case "spiral":
                        mode = "spiral"
                    case _:
                        assert False, f"Mode '{ev['mode']}' not supported."
                reps = rgb_multi_load_settings(
                    mode,
                    0x03,
                    ev["red"],
                    ev["green"],
                    ev["blue"],
                    ev["brightness"],
                    ev["speed"],
                )

            for r in reps:
                dev.write(r)
