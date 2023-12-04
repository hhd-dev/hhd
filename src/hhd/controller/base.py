from concurrent.futures import thread
from functools import partial
from threading import Condition, Event, Lock, Thread
from typing import TypeVar, cast
from enum import Enum
from typing import Generic, TypeVarTuple

"""All axis values are normalized floating point values from -1 to 1."""
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


CB_LOCK = Lock()
CB_COND = Condition(CB_LOCK)


class ThreadedReceiver:
    """Implements the base functionality of a threaded callback, which can set when
    it is available to receive data.

    If it is, it should set `available()` equal to `True`."""

    def __init__(self) -> None:
        self._available = Event()

    @property
    def available(self):
        return self._available.is_set()

    @available.setter
    def available(self, val: bool):
        if val:
            self._available.set()
        else:
            self._available.clear()
        with CB_COND:
            CB_COND.notify_all()


A = TypeVar("A", bound=ThreadedReceiver)


class _CallbackWrapper:
    def __init__(self, fun):
        self.fun = fun

    def __getattr__(self, attr: str):
        return partial(self.fun, attr)


class ThreadedTransmitter(Generic[A]):
    """Implements the base functionality for a threaded component that can respont to
    callbacks. Callbacks types are passed as a generic, `A`, and registered with
    the `register` function.

    Multiple callbacks are supported, and are all wrapped in the `.callback` attribute,
    which may be used by the underlying procedure to respond to all of them.

    The threaded component of this function is achieved through `start()`, `stop()`,
    and `run()`.
    By calling `start()`, the `run()` function is launched on a separate thread.
    When `stop()` is called, the `should_exit` is set to True and the function
    waits for `run()` to exit.
    Therefore, the `run()` function should check it periodically, ideally once per loop
    and always less than per 1s, to ensure the program can close successfully.
    """

    def __init__(self) -> None:
        self.callback: A
        self._callbacks: list[A] = []
        self._should_exit = Event()
        self._thread = None

        # Setup fake callback object to call multiple listeners
        self.callback = cast(A, _CallbackWrapper(self._callback))

    def _callback(self, fun: str, *args, **kwargs):
        with CB_LOCK:
            cbs = list(self._callbacks)
        for cb in cbs:
            getattr(cb, fun)(*args, **kwargs)

    def wait(self):
        with CB_LOCK:
            CB_COND.wait_for(
                lambda: self.should_exit
                or (self._callbacks and any(c.available for c in self._callbacks))
            )

    def start(self):
        self._thread = Thread(target=self.run)
        self._thread.start()

    def stop(self):
        if not self._thread:
            return

        self._should_exit.set()
        with CB_COND:
            CB_COND.notify_all()

        self._thread.join()
        self._thread = None

    @property
    def should_exit(self):
        return self._should_exit.is_set()

    @property
    def exit_event(self):
        return self._should_exit

    def register(self, cb: A):
        with CB_COND:
            if cb not in self._callbacks:
                self._callbacks.append(cb)
            CB_COND.notify_all()

    def unregister(self, cb: A):
        with CB_COND:
            self._callbacks.remove(cb)
            CB_COND.notify_all()

    def run(self):
        raise NotImplementedError()


class ThreadedTransceiver(ThreadedTransmitter[A], ThreadedReceiver, Generic[A]):
    def __init__(self) -> None:
        ThreadedTransmitter.__init__(self)
        ThreadedReceiver.__init__(self)


class PhysicalController(ThreadedReceiver):
    def rumble(self, key: Rumble, val: RumbleMode | int):
        pass

    def config(self, key: Configuration, val: int):
        pass


class VirtualController(ThreadedReceiver):
    def set_axis(self, key: Axis, val: float):
        pass

    def set_btn(self, key: Button, val: bool):
        pass

    def commit(self):
        pass
