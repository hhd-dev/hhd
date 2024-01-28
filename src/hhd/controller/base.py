import logging
import select
import time
from typing import Any, Literal, NamedTuple, Sequence, TypedDict

from .const import Axis, Button, Configuration

logger = logging.getLogger(__name__)


class RumbleEvent(TypedDict):
    """In case ev effects is too complicated. If both magnitudes are 0, disable rumble."""

    type: Literal["rumble"]
    code: Literal["main", "left", "right"]
    strong_magnitude: float
    weak_magnitude: float


class RgbLedEvent(TypedDict):
    """Inspired by new controllers with RGB leds, especially below the buttons.

    Instead of code, this event type exposes multiple properties, including mode."""

    type: Literal["led"]

    # The led
    code: Literal["main", "left", "right"]

    # Various lighting modes supported by the led.
    mode: Literal["disable", "solid", "blinking", "rainbow", "spiral"]

    # Brightness range is from 0 to 1
    # If the response device does not support brightness control, it shall
    # convert the rgb color to hue, assume saturation is 1, and derive a new
    # RGB value from the brightness below
    brightness: float

    # The speed the led should blink if supported by the led
    speed: float

    # Color values for the led, may be ommited depending on the mode, by being
    # set to 0
    red: int
    green: int
    blue: int


class ButtonEvent(TypedDict):
    type: Literal["button"]
    code: Button
    value: bool


class AxisEvent(TypedDict):
    type: Literal["axis"]
    code: Axis
    value: float


class ConfigurationEvent(TypedDict):
    type: Literal["configuration"]
    code: Configuration
    value: Any


Event = ButtonEvent | AxisEvent | ConfigurationEvent | RgbLedEvent | RumbleEvent


class TouchpadCorrection(NamedTuple):
    x_mult: float = 1
    x_ofs: float = 0
    x_clamp: tuple[float, float] = (0, 1)
    y_mult: float = 1
    y_ofs: float = 0
    y_clamp: tuple[float, float] = (0, 1)


TouchpadCorrectionType = Literal[
    "stretch",
    "crop_center",
    "crop_start",
    "crop_end",
    "contain_start",
    "contain_end",
    "contain_center",
    "disabled",
]


def correct_touchpad(
    width: int, height: int, aspect: float, method: TouchpadCorrectionType
):
    dst = width / height
    src = aspect
    ratio = dst / src

    match method:
        case "crop_center":
            if ratio > 1:
                new_width = width / ratio
                return TouchpadCorrection(
                    x_mult=new_width,
                    x_ofs=(width - new_width) / 2,
                    y_mult=height,
                    y_ofs=0,
                )
            else:
                new_height = height * ratio
                return TouchpadCorrection(
                    x_mult=width,
                    x_ofs=0,
                    y_mult=new_height,
                    y_ofs=(height - new_height) / 2,
                )
        case "crop_start":
            if ratio > 1:
                new_width = width / ratio
                return TouchpadCorrection(
                    x_mult=new_width,
                    x_ofs=0,
                    y_mult=height,
                    y_ofs=0,
                )
            else:
                new_height = height * ratio
                return TouchpadCorrection(
                    x_mult=width,
                    x_ofs=0,
                    y_mult=new_height,
                    y_ofs=0,
                )
        case "crop_end":
            if ratio > 1:
                new_width = width / ratio
                return TouchpadCorrection(
                    x_mult=new_width,
                    x_ofs=(width - new_width),
                    y_mult=height,
                    y_ofs=0,
                )
            else:
                new_height = height * ratio
                return TouchpadCorrection(
                    x_mult=width,
                    x_ofs=0,
                    y_mult=new_height,
                    y_ofs=(height - new_height),
                )
        case "contain_center":
            if ratio > 1:
                bound = (ratio - 1) / ratio / 2
                return TouchpadCorrection(
                    x_mult=width, y_mult=height, y_clamp=(bound, 1 - bound)
                )
            else:
                bound = (1 - ratio) / 2
                return TouchpadCorrection(
                    x_mult=width, y_mult=height, x_clamp=(bound, 1 - bound)
                )
        case "contain_start":
            if ratio > 1:
                bound = (ratio - 1) / ratio
                return TouchpadCorrection(
                    x_mult=width, y_mult=height, y_clamp=(0, 1 - bound)
                )
            else:
                bound = (1 - ratio) / 2
                return TouchpadCorrection(
                    x_mult=width, y_mult=height, x_clamp=(0, 1 - bound)
                )
        case "contain_end":
            if ratio > 1:
                bound = (ratio - 1) / ratio
                return TouchpadCorrection(
                    x_mult=width, y_mult=height, y_clamp=(bound, 1)
                )
            else:
                bound = (1 - ratio) / 2
                return TouchpadCorrection(
                    x_mult=width, y_mult=height, x_clamp=(bound, 1)
                )
        case "stretch" | "disabled":
            return TouchpadCorrection(x_mult=width, y_mult=height)

    logger.error(f"Touchpad correction method '{method}' not found.")
    return TouchpadCorrection(x_mult=width, y_mult=height)


class Producer:
    def open(self) -> Sequence[int]:
        """Opens and returns a list of file descriptors that should be listened to."""
        raise NotImplementedError()

    def close(self, exit: bool) -> bool:
        """Called to close the device.

        If `exit` is true, the program is about to
        close. If it is false, the controller is entering power save mode because
        it is unused. In this case, if this service is required, you may forgo
        closing and return false. If true, it is assumed this producer is closed.

        `open()` will be called again once the consumers are ready."""
        return False

    def produce(self, fds: Sequence[int]) -> Sequence[Event]:
        """Called with the file descriptors that are ready to read."""
        return []


class Consumer:
    available: bool
    """Hint that states if the consumer can receive events. If it is false,
    consumer will not be called. If all consumers are false, producers will
    be closed to save CPU utilisation."""

    def initialize(self):
        """Optional method for initialization."""
        pass

    def consume(self, events: Sequence[Event]):
        pass


TouchpadAction = Literal["disabled", "left_click", "right_click"]


class Multiplexer:
    QAM_DELAY = 0.2
    REBOOT_HOLD = 4
    REBOOT_VIBRATION_STRENGTH = 0.6
    REBOOT_VIBRATION_ON = 0.3
    REBOOT_VIBRATION_OFF = 0.8
    REBOOT_VIBRATION_NUM = 3

    def __init__(
        self,
        swap_guide: None | Literal["guide_is_start", "guide_is_select"] = None,
        trigger: None | Literal["analog_to_discrete", "discrete_to_analogue"] = None,
        dpad: None | Literal["analog_to_discrete"] = None,
        led: None | Literal["left_to_main", "right_to_main", "main_to_sides"] = None,
        touchpad: None
        | Literal["left_to_main", "right_to_main", "main_to_sides"] = None,
        status: None | Literal["both_to_main"] = None,
        share_to_qam: bool = False,
        trigger_discrete_lvl: float = 0.99,
        touchpad_short: TouchpadAction = "disabled",
        touchpad_right: TouchpadAction = "left_click",
        touchpad_hold: TouchpadAction = "disabled",
        r3_to_share: bool = False,
        select_reboots: bool = False,
        nintendo_mode: bool = False,
        qam_button: str | None = None,
    ) -> None:
        self.swap_guide = swap_guide
        self.trigger = trigger
        self.dpad = dpad
        self.led = led
        self.touchpad = touchpad
        self.status = status
        self.trigger_discrete_lvl = trigger_discrete_lvl
        self.touchpad_short = touchpad_short
        self.touchpad_hold = touchpad_hold
        self.touchpad_right = touchpad_right
        self.select_reboots = select_reboots
        self.r3_to_share = r3_to_share
        self.nintendo_mode = nintendo_mode

        self.state = {}
        self.touchpad_x = 0
        self.touchpad_y = 0
        self.touchpad_down = None
        self.queue: list[tuple[Event | Literal["reboot"], float]] = []
        self.select_pressed = None
        self.select_is_held = False
        self.qam_button = qam_button
        if share_to_qam:
            self.qam_button = "share"

        assert touchpad is None, "touchpad rewiring not supported yet"

    def process(self, events: Sequence[Event]):
        out: list[Event] = []
        status_events = set()
        touched = False

        curr = time.perf_counter()
        while len(self.queue) and self.queue[0][1] < curr:
            ev = self.queue.pop(0)[0]
            if ev == "reboot":
                if self.select_is_held:
                    try:
                        import os

                        os.system("systemctl reboot")
                        logger.info("rebooting")
                    except Exception as e:
                        logger.error(f"Rebooting failed with error:\n{type(e)}:{e}")
            elif self.select_is_held or not ev.get("from_reboot", False):
                out.append(ev)

        if self.select_pressed and self.select_pressed + self.REBOOT_HOLD < curr:
            self.select_pressed = None
            for i in range(self.REBOOT_VIBRATION_NUM):
                self.queue.append(
                    (
                        {
                            "type": "rumble",
                            "code": "main",
                            "strong_magnitude": self.REBOOT_VIBRATION_STRENGTH,
                            "weak_magnitude": self.REBOOT_VIBRATION_STRENGTH,
                            "from_reboot": True,
                        },  # type: ignore
                        curr
                        + i * (self.REBOOT_VIBRATION_ON + self.REBOOT_VIBRATION_OFF),
                    )
                )
                self.queue.append(
                    (
                        {
                            "type": "rumble",
                            "code": "main",
                            "strong_magnitude": 0,
                            "weak_magnitude": 0,
                        },
                        curr
                        + i * (self.REBOOT_VIBRATION_ON + self.REBOOT_VIBRATION_OFF)
                        + self.REBOOT_VIBRATION_ON,
                    )
                )
            self.queue.append(("reboot", curr))

        if (
            self.touchpad_hold != "disabled"
            and self.touchpad_down
            and curr - self.touchpad_down[0] > 0.8
            and abs(self.touchpad_down[1] - self.touchpad_x) < 0.1
            and abs(self.touchpad_down[2] - self.touchpad_y) < 0.1
        ):
            action = (
                "touchpad_left"
                if self.touchpad_hold == "left_click"
                else "touchpad_right"
            )
            self.queue.append(
                (
                    {
                        "type": "button",
                        "code": action,
                        "value": True,
                    },
                    curr,
                )
            )
            self.queue.append(
                (
                    {
                        "type": "button",
                        "code": action,
                        "value": False,
                    },
                    curr + self.QAM_DELAY,
                )
            )
            self.touchpad_down = None

        for ev in events:
            match ev["type"]:
                case "axis":
                    if self.trigger == "analog_to_discrete" and ev["code"] in (
                        "lt",
                        "rt",
                    ):
                        out.append(
                            {
                                "type": "button",
                                "code": ev["code"],
                                "value": ev["value"] > self.trigger_discrete_lvl,
                            }
                        )

                    if self.dpad == "analog_to_discrete" and ev["code"] in (
                        "hat_x",
                        "hat_y",
                    ):
                        out.append(
                            {
                                "type": "button",
                                "code": "dpad_up"
                                if ev["code"] == "hat_y"
                                else "dpad_right",
                                "value": ev["value"] > 0.5,
                            }
                        )
                        out.append(
                            {
                                "type": "button",
                                "code": "dpad_down"
                                if ev["code"] == "hat_y"
                                else "dpad_left",
                                "value": ev["value"] < -0.5,
                            }
                        )
                    if ev["code"] == "touchpad_x":
                        self.touchpad_x = ev["value"]
                    if ev["code"] == "touchpad_y":
                        self.touchpad_y = ev["value"]
                case "button":
                    if self.trigger == "discrete_to_analog" and ev["code"] in (
                        "lt",
                        "rt",
                    ):
                        out.append(
                            {
                                "type": "axis",
                                "code": ev["code"],
                                "value": 1 if ev["value"] else 0,
                            }
                        )

                    if self.swap_guide and ev["code"] in (
                        "start",
                        "select",
                        "mode",
                        "share",
                    ):
                        match ev["code"]:
                            case "start":
                                ev["code"] = "mode"
                            case "select":
                                ev["code"] = "share"
                            case "mode":
                                if self.swap_guide == "guide_is_start":
                                    ev["code"] = "start"
                                else:
                                    ev["code"] = "select"
                            case "share":
                                if self.swap_guide == "guide_is_start":
                                    ev["code"] = "select"
                                else:
                                    ev["code"] = "start"

                    if self.select_reboots and ev["code"] == "select":
                        if ev["value"]:
                            self.select_is_held = True
                            self.select_pressed = curr
                        else:
                            self.select_is_held = False
                            self.select_pressed = None

                    if self.qam_button is not None and ev["code"] == self.qam_button:
                        if ev["value"]:
                            ev["code"] = "mode"
                            self.queue.append(
                                (
                                    {
                                        "type": "button",
                                        "code": "a",
                                        "value": True,
                                    },
                                    curr + self.QAM_DELAY,
                                )
                            )
                        else:
                            # TODO: Clean this up
                            ev["code"] = ""  # type: ignore
                            self.queue.append(
                                (
                                    {
                                        "type": "button",
                                        "code": "mode",
                                        "value": False,
                                    },
                                    curr + self.QAM_DELAY,
                                ),
                            )
                            self.queue.append(
                                (
                                    {
                                        "type": "button",
                                        "code": "a",
                                        "value": False,
                                    },
                                    curr + self.QAM_DELAY,
                                ),
                            )

                    if ev["code"] == "touchpad_right":
                        match self.touchpad_right:
                            case "disabled":
                                # TODO: Cleanup
                                ev["code"] = ""  # type: ignore
                            case "left_click":
                                ev["code"] = "touchpad_left"
                            case "right_click":
                                pass

                    if ev["code"] == "touchpad_touch":
                        if (
                            self.touchpad_short != "disabled"
                            and not ev["value"]
                            and self.touchpad_down
                            and curr - self.touchpad_down[0] < 0.2
                            and abs(self.touchpad_down[1] - self.touchpad_x) < 0.04
                            and abs(self.touchpad_down[2] - self.touchpad_y) < 0.04
                        ):
                            action = (
                                "touchpad_left"
                                if self.touchpad_short == "left_click"
                                else "touchpad_right"
                            )
                            self.queue.append(
                                (
                                    {
                                        "type": "button",
                                        "code": action,
                                        "value": True,
                                    },
                                    curr,
                                )
                            )
                            self.queue.append(
                                (
                                    {
                                        "type": "button",
                                        "code": action,
                                        "value": False,
                                    },
                                    curr + self.QAM_DELAY,
                                )
                            )

                        if ev["value"]:
                            touched = True
                        else:
                            self.touchpad_down = None
                        # append A after QAM_DELAY s

                    if self.r3_to_share and ev["code"] == "extra_r3":
                        ev["code"] = "share"

                    if self.nintendo_mode:
                        match ev["code"]:
                            case "a":
                                ev["code"] = "b"
                            case "b":
                                ev["code"] = "a"
                            case "x":
                                ev["code"] = "y"
                            case "y":
                                ev["code"] = "x"
                case "led":
                    if self.led == "left_to_main" and ev["code"] == "left":
                        out.append({**ev, "code": "main"})
                    elif self.led == "right_to_main" and ev["code"] == "right":
                        out.append({**ev, "code": "main"})
                    elif self.led == "main_to_both" and ev["code"] == "main":
                        out.append({**ev, "code": "left"})
                        out.append({**ev, "code": "right"})
                case "configuration":
                    if self.status == "both_to_main":
                        self.state[ev["code"]] = ev["value"]
                        match ev["code"]:
                            case "battery_left" | "battery_right":
                                status_events.add("battery")
                            case "is_attached_left" | "is_attached_right":
                                status_events.add("is_attached")
                            case "is_connected_left" | "is_connected_right":
                                status_events.add("is_connected")

        if touched:
            self.touchpad_down = (
                curr,
                self.touchpad_x,
                self.touchpad_y,
            )

        for s in status_events:
            match s:
                case "battery":
                    out.append(
                        {
                            "type": "configuration",
                            "code": "battery",
                            "value": min(
                                self.state.get("battery_left", 100),
                                self.state.get("battery_right", 100),
                            ),
                        }
                    )
                case "is_attached":
                    out.append(
                        {
                            "type": "configuration",
                            "code": "is_attached",
                            "value": (
                                self.state.get("is_attached_left", False)
                                and self.state.get("is_attached_right", False)
                            ),
                        }
                    )
                case "is_connected":
                    out.append(
                        {
                            "type": "configuration",
                            "code": "is_connected",
                            "value": (
                                self.state.get("is_connected_left", False)
                                and self.state.get("is_connected_right", False)
                            ),
                        }
                    )

        out.extend(events)
        return out


class KeyboardWrapper(Producer, Consumer):
    def __init__(
        self, parent: Producer, button_map: Sequence[tuple[set[Button], Button]]
    ) -> None:
        self.parent = parent
        self.button_map = button_map

        self.active_in: set[Button] = set()
        self.active_out: set[Button] = set()

    def open(self) -> Sequence[int]:
        self.active_in: set[Button] = set()
        self.active_out: set[Button] = set()
        return self.parent.open()

    def close(self, exit: bool) -> bool:
        return self.parent.close(exit)

    def produce(self, fds: Sequence[int]) -> Sequence[Event]:
        evs: Sequence[Event] = self.parent.produce(fds)
        # Update in map
        for ev in evs:
            logger.info(f"Internal kbd event: {ev}")
            if ev["type"] == "button":
                if ev["value"]:
                    self.active_in.add(ev["code"])
                elif ev["code"] in self.active_in:
                    self.active_in.remove(ev["code"])

        # Debounce and output
        out: Sequence[Event] = []
        for bset, action in self.button_map:
            is_sub = bset.issubset(self.active_in)
            is_active = action in self.active_out
            if is_sub and not is_active:
                self.active_out.add(action)
                out.append({"type": "button", "code": action, "value": True})
            elif not is_sub and is_active:
                self.active_out.remove(action)
                out.append({"type": "button", "code": action, "value": False})

        return out

    def consume(self, events: Sequence[Event]):
        if isinstance(self.parent, Consumer):
            return self.parent.consume(events)


def can_read(fd: int):
    return select.select([fd], [], [], 0)[0]
