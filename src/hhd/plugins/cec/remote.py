import logging
import time
from collections.abc import Callable

from evdev import UInput, ecodes

from .cec import (
    CEC_MSG_USER_CONTROL_PRESSED,
    CEC_MSG_USER_CONTROL_RELEASED,
    CEC_OP_UI_CMD_BACK,
    CEC_OP_UI_CMD_DOWN,
    CEC_OP_UI_CMD_ENTER,
    CEC_OP_UI_CMD_LEFT,
    CEC_OP_UI_CMD_RIGHT,
    CEC_OP_UI_CMD_SELECT,
    CEC_OP_UI_CMD_UP,
    CecMsg,
)

logger = logging.getLogger(__name__)

HOLD_TIME = 0.4
DOUBLE_PRESS_TIME = 0.2

KEY_MAP = {
    CEC_OP_UI_CMD_SELECT: ecodes.KEY_ENTER,
    CEC_OP_UI_CMD_ENTER: ecodes.KEY_ENTER,
    CEC_OP_UI_CMD_UP: ecodes.KEY_UP,
    CEC_OP_UI_CMD_DOWN: ecodes.KEY_DOWN,
    CEC_OP_UI_CMD_LEFT: ecodes.KEY_LEFT,
    CEC_OP_UI_CMD_RIGHT: ecodes.KEY_RIGHT,
}


class TvRemote:
    def __init__(self, emit: Callable | None):
        self.emit = emit
        self.uinput: UInput | None = None
        self.pressed_command: int | None = None
        self.pressed_key: int | None = None
        self.back_pressed_at: float | None = None
        self.back_released_at: float | None = None
        self.back_presses = 0
        self.back_held = False

    def open(self):
        if self.uinput:
            return
        self.uinput = UInput(
            {ecodes.EV_KEY: sorted({*KEY_MAP.values(), ecodes.KEY_ESC})},
            name="Handheld Daemon TV Remote",
            phys="phys-hhd-cec",
        )

    def _key(self, key: int, value: int):
        if not self.uinput:
            return
        self.uinput.write(ecodes.EV_KEY, key, value)
        self.uinput.syn()

    def _event(self, event: str):
        if self.emit:
            self.emit({"type": "special", "event": event})

    def _release(self, now: float):
        if self.pressed_key is not None:
            self._key(self.pressed_key, 0)
            self.pressed_key = None
        if self.pressed_command == CEC_OP_UI_CMD_BACK:
            if self.back_held:
                self.back_pressed_at = None
                self.back_released_at = None
                self.back_presses = 0
                self.back_held = False
            elif self.back_pressed_at is not None:
                self.back_pressed_at = None
                self.back_released_at = now
                self.back_presses += 1
        self.pressed_command = None

    def handle(self, msg: CecMsg, now: float | None = None):
        now = time.monotonic() if now is None else now
        self.tick(now)
        opcode = int(msg.msg[1])
        if opcode == CEC_MSG_USER_CONTROL_RELEASED:
            self._release(now)
            return
        if opcode != CEC_MSG_USER_CONTROL_PRESSED or msg.len < 3:
            return

        command = int(msg.msg[2])
        if command == self.pressed_command:
            if self.pressed_key is not None:
                self._key(self.pressed_key, 2)
            return
        if self.pressed_command is not None:
            self._release(now)

        self.pressed_command = command
        if command == CEC_OP_UI_CMD_BACK:
            self.back_pressed_at = now
            return
        if key := KEY_MAP.get(command):
            self.pressed_key = key
            self._key(key, 1)

    def tick(self, now: float | None = None):
        now = time.monotonic() if now is None else now
        if (
            self.back_pressed_at is not None
            and not self.back_held
            and now - self.back_pressed_at >= HOLD_TIME
        ):
            self.back_held = True
            self.back_released_at = None
            self.back_presses = 0
            self._event("cec_back_hold")
        elif (
            self.back_pressed_at is None
            and self.back_released_at is not None
            and now - self.back_released_at >= DOUBLE_PRESS_TIME
        ):
            if self.back_presses == 1:
                self._key(ecodes.KEY_ESC, 1)
                self._key(ecodes.KEY_ESC, 0)
            elif self.back_presses == 2:
                self._event("cec_back_double")
            elif self.back_presses >= 3:
                self._event("cec_back_triple")
            self.back_released_at = None
            self.back_presses = 0

    def reset(self):
        if self.pressed_key is not None:
            self._key(self.pressed_key, 0)
        self.pressed_command = None
        self.pressed_key = None
        self.back_pressed_at = None
        self.back_released_at = None
        self.back_presses = 0
        self.back_held = False

    def close(self):
        self.reset()
        if self.uinput:
            self.uinput.close()
            self.uinput = None
