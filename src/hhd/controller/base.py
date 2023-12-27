import select
from typing import Any, Literal, Sequence, TypedDict
import time
from .const import Axis, Button, Configuration


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


Event = (
    ButtonEvent
    | AxisEvent
    | ConfigurationEvent
    | RgbLedEvent
    | RumbleEvent
)


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


class Multiplexer:
    QAM_DELAY = 0.2

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
    ) -> None:
        self.swap_guide = swap_guide
        self.trigger = trigger
        self.dpad = dpad
        self.led = led
        self.touchpad = touchpad
        self.status = status
        self.trigger_discrete_lvl = trigger_discrete_lvl
        self.share_to_qam = share_to_qam

        self.state = {}
        self.queue: list[tuple[Event, float]] = []

        assert touchpad is None, "touchpad rewiring not supported yet"

    def process(self, events: Sequence[Event]):
        out: list[Event] = []
        status_events = set()

        curr = time.perf_counter()
        while len(self.queue) and self.queue[0][1] < curr:
            out.append(self.queue.pop(0)[0])

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

                    if self.share_to_qam and ev["code"] == "share":
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

                        # append A after QAM_DELAY s

                    # TODO: Make it a proper config option
                    # Remap M2 to the mute button
                    if ev["code"] == "extra_r3":
                        ev["code"] = "share"
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


def can_read(fd: int):
    return select.select([fd], [], [], 0)[0]
