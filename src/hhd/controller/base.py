from typing import Any, Literal, Sequence, TypedDict

Axis = Literal[
    # Sticks
    # Values should range from -1 to 1
    "ls_x",
    "ls_y",
    "rs_x",
    "rs_y",
    # Triggers
    # Values should range from -1 to 1
    "lt",
    "rt",
    # Hat, implemented as axis. Either -1, 0, or 1
    "hat_x",
    "hat_y",
    # Accelerometer
    # Values should be in m2/s
    "accel_x",
    "accel_y",
    "accel_z",
    # Gyroscope
    # Values should be in deg/s
    "gyro_x",
    "gyro_y",
    "gyro_z",
    # Touchpad
    # Both width and height should go from [0, 1]. Aspect ratio is a setting.
    # It is up to the device whether to stretch, crop and how to crop (either 
    # crop part of the input or part of itself)
    "touchpad_x",
    "touchpad_y",
]


Button = Literal[
    # Thumbpad
    "a",
    "b",
    "x",
    "y",
    # Sticks
    "ls",
    "rs",
    # Bumpers
    "lb",
    "rb",
    # Back buttons
    "extra_l1",
    "extra_l2",
    "extra_l3",
    "extra_r1",
    "extra_r2",
    "extra_r3",
    # Select
    "start",
    "select",
    # Misc
    "mode",
    "share",
    "touchpad_touch",
    "touchpad_click",
]


Configuration = Literal[
    # Misc
    "led_mute",  # binary
    "player",
    # Set the aspect ratio of the touchpad used
    "touchpad_aspect_ratio",
]


class RumbleEvent(TypedDict):
    type: Literal["rumble"]
    # Rumble side, if the controller has left/right rubmles.
    # Producers that control rumble should either use `left`/`right` or `both`.
    # But not both. Consumers that support 2 rumble and see `both` should set the
    # color of both rumble. Consumers that have a single rumble and see 'left` or `right`
    # shall use the last value or pick a random side (TODO: Determine if there
    # are issues with either approach).
    side: Literal["both", "left", "right"]
    mode: Literal["disable", "square", "cross", "circle", "triangle"]
    intensity: float


class LedEvent(TypedDict):
    type: Literal["led"]

    # Led side, if the controller has left/right leds.
    # Producers that control leds should either use `left`/`right` or `both`.
    # But not both. Consumers that support 2 leds and see `both` should set the
    # color of both leds. Consumers that support 1 LED and see 'left` or `right`
    # shall use the last value or pick a random side (TODO: Determine if there
    # are issues with either approach).
    led: Literal["both", "left", "right"]

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
    button: Button
    held: int


class AxisEvent(TypedDict):
    type: Literal["axis"]
    axis: Axis
    val: float


class ConfigurationEvent(TypedDict):
    type: Literal["configuration"]
    conf: Configuration
    val: Any


Event = RumbleEvent | ButtonEvent | AxisEvent | ConfigurationEvent


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
        raise NotImplementedError()


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
