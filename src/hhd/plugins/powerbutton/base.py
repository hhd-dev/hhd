import ctypes
import logging
import os
import select
import struct
from dataclasses import dataclass
from fcntl import ioctl
from threading import Event
from time import perf_counter
from typing import Iterable, Literal, cast

import evdev

from hhd.controller.lib.ioctl import EVIOCSMASK
from hhd.utils import is_steam_gamepad_running, run_steam_command

from ..power.power import emergency_hibernate, supports_sleep

logger = logging.getLogger(__name__)

STEAM_WAIT_DELAY = 0.5
RESCAN_DELAY = 0.5
LONG_PRESS_DELAY = 2.0
DEBOUNCE_DELAY = 1.0
SLEEP_MIN = 2.0

LOGIN1_BUS = "org.freedesktop.login1"
LOGIN1_PATH = "/org/freedesktop/login1"
LOGIN1_INTERFACE = "org.freedesktop.login1.Manager"
INHIBIT_WHAT = "handle-power-key:handle-lid-switch"

PowerAction = Literal["short", "long"]


def B(b: str) -> int:
    return cast(int, getattr(evdev.ecodes, b))


class LogindInhibitor:
    """Hold a logind inhibitor for as long as its returned fd remains open."""

    def __init__(self) -> None:
        self.fd: int | None = None
        self.bus = None

    @property
    def active(self) -> bool:
        return self.fd is not None

    def acquire(self) -> bool:
        if self.active:
            return True

        try:
            import dbus

            self.bus = dbus.SystemBus()
            manager = self.bus.get_object(LOGIN1_BUS, LOGIN1_PATH)
            inhibit = manager.get_dbus_method("Inhibit", LOGIN1_INTERFACE)
            inhibitor_fd = inhibit(
                INHIBIT_WHAT,
                "HandheldDaemon",
                "Handheld Daemon handles power and lid events",
                "block",
            )
            self.fd = inhibitor_fd.take()
            logger.info("Inhibited logind power button and lid switch handling.")
            return True
        except Exception as e:
            logger.error(f"Could not inhibit logind power handling:\n{e}")
            self.release()
            return False

    def release(self) -> None:
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
        self.fd = None
        self.bus = None


def _event_codes(device: evdev.InputDevice, event_type: int) -> set[int]:
    try:
        return set(device.capabilities().get(event_type, []))
    except Exception:
        return set()


def is_power_device(device: evdev.InputDevice) -> bool:
    name = (device.name or "").casefold()
    return (
        "power button" in name
        or "lid switch" in name
        or B("KEY_POWER") in _event_codes(device, B("EV_KEY"))
        or B("SW_LID") in _event_codes(device, B("EV_SW"))
    )


def set_evdev_mask(fd: int, event_type: int, codes: Iterable[int]) -> None:
    codes = tuple(codes)
    if codes:
        size = max((max(codes) >> 3) + 1, 8)
        size += -size % 8
    else:
        size = 0
    mask = bytearray(size)
    for code in codes:
        mask[code >> 3] |= 1 << (code & 0x07)

    c_mask = ctypes.create_string_buffer(bytes(mask))
    data = struct.pack("=IIQ", event_type, size, ctypes.addressof(c_mask))
    ioctl(fd, EVIOCSMASK, data)


def mask_power_events(device: evdev.InputDevice) -> None:
    """Filter this fd so unrelated events never enter its evdev queue."""
    # EV_SYN is special: its mask selects allowed event types rather than SYN
    # codes. Set every mask unconditionally; unused bits are harmless.
    set_evdev_mask(device.fd, B("EV_SYN"), (B("EV_KEY"), B("EV_SW")))
    set_evdev_mask(device.fd, B("EV_KEY"), (B("KEY_POWER"),))
    set_evdev_mask(device.fd, B("EV_SW"), (B("SW_LID"),))


def reconcile_power_devices(
    devices: dict[str, evdev.InputDevice],
    ignored_paths: set[str] | None = None,
) -> dict[str, evdev.InputDevice]:
    """Reconcile eligible evdev nodes without ever taking an exclusive grab."""
    if ignored_paths is None:
        ignored_paths = set()

    try:
        paths = set(evdev.list_devices())
    except Exception as e:
        logger.warning(f"Could not list input devices:\n{e}")
        return devices

    for path in set(devices) - paths:
        logger.info(f"Power input device disappeared: '{path}'.")
        try:
            devices[path].close()
        except Exception:
            pass
        del devices[path]

    ignored_paths.intersection_update(paths)
    for path in paths - set(devices) - ignored_paths:
        try:
            device = evdev.InputDevice(path)
            if not is_power_device(device):
                device.close()
                ignored_paths.add(path)
                continue
            try:
                mask_power_events(device)
            except OSError as e:
                logger.warning(f"Could not mask input device '{path}', skipping: {e}")
                device.close()
                ignored_paths.add(path)
                continue
            devices[path] = device
            logger.info(
                f"Monitoring power input '{device.name}': '{device.phys}' ({path})."
            )
        except Exception as e:
            logger.debug(f"Could not inspect input device '{path}': {e}")

    return devices


def close_power_devices(devices: dict[str, evdev.InputDevice]) -> None:
    for device in devices.values():
        try:
            device.close()
        except Exception:
            pass
    devices.clear()


def quarantine_power_device(
    devices: dict[str, evdev.InputDevice], ignored_paths: set[str], path: str
) -> None:
    device = devices.pop(path, None)
    if device is not None:
        try:
            device.close()
        except Exception:
            pass
    # evdev may keep returning a dead node briefly. Reconciliation removes this
    # quarantine as soon as the path disappears, allowing a later reconnect.
    ignored_paths.add(path)


@dataclass
class PowerEventState:
    pressed_at: float | None = None
    last_action_at: float | None = None
    last_cycle_at: float | None = None
    blocked_until: float = 0.0

    def reset(self) -> None:
        self.pressed_at = None
        self.last_action_at = None
        self.last_cycle_at = None
        self.blocked_until = 0.0

    def begin_cycle(self, now: float) -> None:
        if self.last_cycle_at is not None and now - self.last_cycle_at > SLEEP_MIN:
            # Input events generated during suspend can be delivered after resume.
            self.pressed_at = None
            self.blocked_until = now + DEBOUNCE_DELAY
        self.last_cycle_at = now

    def _action(self, action: PowerAction, now: float) -> PowerAction | None:
        if now < self.blocked_until:
            self.pressed_at = None
            return None
        if (
            self.last_action_at is not None
            and now - self.last_action_at <= DEBOUNCE_DELAY
        ):
            self.pressed_at = None
            return None

        self.pressed_at = None
        self.last_action_at = now
        return action

    def handle(self, event: evdev.InputEvent, now: float) -> PowerAction | None:
        if event.type == B("EV_KEY") and event.code == B("KEY_POWER"):
            if event.value == 1:
                if now >= self.blocked_until and (
                    self.last_action_at is None
                    or now - self.last_action_at > DEBOUNCE_DELAY
                ):
                    if self.pressed_at is None:
                        self.pressed_at = now
            elif event.value == 0 and self.pressed_at is not None:
                action: PowerAction = (
                    "long" if now - self.pressed_at >= LONG_PRESS_DELAY else "short"
                )
                return self._action(action, now)
            return None

        if event.type == B("EV_SW") and event.code == B("SW_LID") and event.value == 1:
            return self._action("short", now)

        return None

    def timeout(self, now: float) -> PowerAction | None:
        if self.pressed_at is None or now - self.pressed_at < LONG_PRESS_DELAY:
            return None
        return self._action("long", now)

    def poll_timeout(self, now: float) -> float:
        if self.pressed_at is None:
            return STEAM_WAIT_DELAY
        return max(
            0.0,
            min(
                STEAM_WAIT_DELAY,
                LONG_PRESS_DELAY - (now - self.pressed_at),
            ),
        )


_supports_sleep = None


def run_steam_shortpress() -> bool:
    global _supports_sleep
    if _supports_sleep is None:
        _supports_sleep = supports_sleep()

    if _supports_sleep:
        return run_steam_command("steam://shortpowerpress")

    emergency_hibernate(shutdown=False)
    return True


def run_steam_longpress() -> bool:
    return run_steam_command("steam://longpowerpress")


def execute_power_action(action: PowerAction, emit) -> None:
    logger.info(f"Executing {action} power button press.")
    if action == "short":
        worked = run_steam_shortpress()
        emit({"type": "special", "event": "pbtn_short"})
    else:
        worked = run_steam_longpress()
        emit({"type": "special", "event": "pbtn_long"})

    if not worked:
        logger.error("Power button action did not work. Calling `systemctl suspend`")
        os.system("systemctl suspend")


def power_button_run(should_exit: Event, emit) -> None:
    devices: dict[str, evdev.InputDevice] = {}
    ignored_paths: set[str] = set()
    inhibitor = LogindInhibitor()
    state = PowerEventState()
    last_scan = 0.0

    logger.info("Starting generic power button and lid switch handler.")
    try:
        while not should_exit.is_set():
            if not is_steam_gamepad_running():
                if devices or inhibitor.active:
                    logger.info("Steam exited, releasing power input handling.")
                inhibitor.release()
                close_power_devices(devices)
                state.reset()
                should_exit.wait(STEAM_WAIT_DELAY)
                continue

            now = perf_counter()
            if now - last_scan >= RESCAN_DELAY:
                reconcile_power_devices(devices, ignored_paths)
                last_scan = now

            if not devices:
                inhibitor.release()
                state.reset()
                should_exit.wait(STEAM_WAIT_DELAY)
                continue

            if not inhibitor.active and not inhibitor.acquire():
                # Without the inhibitor logind would act on the same events.
                close_power_devices(devices)
                state.reset()
                should_exit.wait(STEAM_WAIT_DELAY)
                continue

            fds = {device.fd: (path, device) for path, device in devices.items()}
            try:
                readable = select.select(list(fds), [], [], state.poll_timeout(now))[0]
            except (OSError, ValueError) as e:
                logger.warning(f"Power input polling failed, rescanning:\n{e}")
                inhibitor.release()
                close_power_devices(devices)
                state.reset()
                continue

            now = perf_counter()
            state.begin_cycle(now)
            actions: list[PowerAction] = []
            for fd in readable:
                path, device = fds[fd]
                try:
                    for event in device.read():
                        if action := state.handle(event, now):
                            actions.append(action)
                except (OSError, BlockingIOError) as e:
                    logger.info(f"Power input '{path}' was removed: {e}")
                    quarantine_power_device(devices, ignored_paths, path)

            if action := state.timeout(now):
                actions.append(action)
            for action in actions:
                execute_power_action(action, emit)

            if not devices:
                inhibitor.release()
                state.reset()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logger.error(f"Received exception, exiting power handler:\n{e}")
    finally:
        inhibitor.release()
        close_power_devices(devices)
