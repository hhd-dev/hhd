from threading import Lock, Thread
from typing import TypeVar
from enum import Enum
from typing import Generic, TypeVarTuple

"""All axis values are signed 16 bit (-32768 to 32767).
If a device does not support 16 bit (and most do not), it shall shift
the values approprietly (v << (16 - A) where A is its bit width)."""
Axis = Enum(
    "Axis",
    [
        # Sticks
        "LEFT_STICK_X",
        "LEFT_STICK_Y",
        "RIGHT_STICK_X",
        "RIGHT_STICK_Y",
        # Triggers
        "LEFT_TRIGGER",
        "RIGHT_TRIGGER",
        # Accelerometer
        "ACCEL_X",
        "ACCEL_Y",
        "ACCEL_Z",
        # Gyroscope
        "GYRO_X",
        "GYRO_Y",
        "GYRO_Z",
        # Touchpad
        "TOUCHPAD_X",
        "TOUCHPAD_Y",
    ],
)

Button = Enum(
    "Button",
    [
        # D-PAD
        "DPAD_UP",
        "DPAD_DOWN",
        "DPAD_LEFT",
        "DPAD_RIGHT",
        # Thumbpad
        "A",
        "B",
        "X",
        "Y",
        # Sticks
        "LS",
        "RS",
        # Bumpers
        "LB",
        "RB",
        # Back buttons
        "EXTRA_L1",
        "EXTRA_L2",
        "EXTRA_L3",
        "EXTRA_R1",
        "EXTRA_R2",
        "EXTRA_R3",
        # Select
        "START",
        "SELECT",
        # Misc
        "GUIDE",
        "SHARE",
        "TOUCHPAD",
    ],
)

"""Rumble may be reported for the controller as a whole, or the sides."""
Rumble = Enum("Rumble", ["MODE", "INTENSITY", "INTENSITY_LEFT", "INTENSITY_RIGHT"])
RumbleMode = Enum("RumbleMode", ["SQUARE", "CROSS", "CIRCLE", "TRIANGLE"])

Configuration = Enum(
    "Configuration",
    [
        # If the virtual controller has a single led, it shall use LED_#
        # The actual controller should set all LEDS on the controller if it has multiple.
        # Color is 3 bytes for RGB, given as an int.
        "LED_COLOR",
        # Brightness is 1 byte, for 256 levels
        # If the response device does not support brightness control, it shall
        # convert the rgb color to hue, assume saturation is 1, and derive a new
        # RGB value from the brightness below
        "LED_BRIGHTNESS",
        # The controller might report colors individually.
        "LED_RIGHT_COLOR",
        "LED_RIGHT_BRIGHTNESS",
        "LED_LEFT_COLOR",
        "LED_LEFT_BRIGHTNESS",
        # Misc
        "LED_MUTE",  # Binary
        "PLAYER",
    ],
)

A = TypeVar("A")


class Handler(A, Generic[A]):
    def __init__(self) -> None:
        self.callbacks: list[A] = []

    def handle(self, fun: str, *args, **kwargs):
        for cb in self.callbacks:
            getattr(cb, fun)(*args, **kwargs)

    def register(self, cb: A):
        if cb not in self.callbacks:
            self.callbacks.append(cb)

    def unregister(self, cb: A):
        self.callbacks.remove(cb)


class ThreadedLoop(Generic[A]):
    handler = Handler[A]()
    _should_exit = False

    _thread = None
    _lock = None

    def start(self):
        self._lock = Lock()
        self._thread = Thread()
        self._thread.start()

    def stop(self):
        if not self._thread:
            return

        assert self._lock
        with self._lock:
            self._should_exit = True

        self._thread.join()
        self._lock = None
        self._thread = None

    @property
    def should_exit(self):
        assert self._lock
        with self._lock:
            return self._should_exit

    def register(self, callback: A):
        self.handler.register(callback)

    def unregister(self, callback: A):
        self.handler.unregister(callback)

    def run(self):
        raise NotImplementedError()


class PeripheralActuator:
    def rumble(self, key: Rumble, val: RumbleMode | int):
        pass

    def config(self, key: Configuration, val: int):
        pass


class VirtualController(ThreadedLoop[PeripheralActuator]):
    def set_axis(self, key: Axis, val: int):
        pass

    def set_btn(self, key: Button, val: bool):
        pass

    def flush(self):
        pass


class PeripheralInterface(ThreadedLoop[VirtualController]):
    pass
