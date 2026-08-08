import ctypes
import struct
import sys
import unittest
from unittest.mock import MagicMock, patch

import evdev

from hhd.plugins.powerbutton import PowerbuttondPlugin, autodetect
from hhd.plugins.powerbutton.base import (
    B,
    DEBOUNCE_DELAY,
    INHIBIT_WHAT,
    LOGIN1_BUS,
    LOGIN1_INTERFACE,
    LOGIN1_PATH,
    LONG_PRESS_DELAY,
    LogindInhibitor,
    PowerEventState,
    close_power_devices,
    is_power_device,
    mask_power_events,
    power_button_run,
    quarantine_power_device,
    reconcile_power_devices,
    set_evdev_mask,
)
from hhd.controller.lib.ioctl import EVIOCSMASK


class FakeDevice:
    next_fd = 100

    def __init__(self, path, name="Other", capabilities=None):
        self.path = path
        self.name = name
        self.phys = "test/input0"
        self._capabilities = capabilities or {}
        self.closed = False
        self.fd = FakeDevice.next_fd
        FakeDevice.next_fd += 1

    def capabilities(self):
        return self._capabilities

    def close(self):
        self.closed = True

    def read(self):
        return []


def input_event(event_type, code, value):
    return evdev.InputEvent(0, 0, event_type, code, value)


class PowerDeviceDiscoveryTest(unittest.TestCase):
    def test_recognizes_names_and_capabilities(self):
        devices = [
            FakeDevice("/dev/name-power", name="Power Button"),
            FakeDevice("/dev/name-lid", name="Lid Switch"),
            FakeDevice(
                "/dev/key-power",
                capabilities={B("EV_KEY"): [B("KEY_POWER")]},
            ),
            FakeDevice(
                "/dev/switch-lid",
                capabilities={B("EV_SW"): [B("SW_LID")]},
            ),
        ]

        for device in devices:
            with self.subTest(device=device.path):
                self.assertTrue(is_power_device(device))

        self.assertFalse(is_power_device(FakeDevice("/dev/other")))

    def test_reconciles_devices_without_grabbing(self):
        power = FakeDevice(
            "/dev/input/event1",
            capabilities={B("EV_KEY"): [B("KEY_POWER")]},
        )
        other = FakeDevice("/dev/input/event2")
        by_path = {power.path: power, other.path: other}

        ignored_paths = set()
        with (
            patch(
                "hhd.plugins.powerbutton.base.evdev.list_devices",
                return_value=list(by_path),
            ),
            patch(
                "hhd.plugins.powerbutton.base.evdev.InputDevice",
                side_effect=by_path.get,
            ),
            patch("hhd.plugins.powerbutton.base.mask_power_events") as mask,
        ):
            devices = reconcile_power_devices({}, ignored_paths)

        self.assertEqual(devices, {power.path: power})
        self.assertEqual(ignored_paths, {other.path})
        self.assertTrue(other.closed)
        self.assertFalse(hasattr(power, "grab"))
        mask.assert_called_once_with(power)

        with patch("hhd.plugins.powerbutton.base.evdev.list_devices", return_value=[]):
            reconcile_power_devices(devices)
        self.assertEqual(devices, {})
        self.assertTrue(power.closed)

    def test_reconcile_retries_devices_that_failed_to_open(self):
        power = FakeDevice("/dev/input/event1", name="Power Button")
        with (
            patch(
                "hhd.plugins.powerbutton.base.evdev.list_devices",
                return_value=[power.path],
            ),
            patch(
                "hhd.plugins.powerbutton.base.evdev.InputDevice",
                side_effect=[OSError("busy"), power],
            ) as input_device,
            patch("hhd.plugins.powerbutton.base.mask_power_events"),
        ):
            devices = reconcile_power_devices({})
            self.assertEqual(devices, {})
            devices = reconcile_power_devices(devices)

        self.assertEqual(devices, {power.path: power})
        self.assertEqual(input_device.call_count, 2)

    def test_mask_failure_skips_device(self):
        power = FakeDevice("/dev/input/event1", name="Power Button")
        ignored_paths = set()
        with (
            patch(
                "hhd.plugins.powerbutton.base.evdev.list_devices",
                return_value=[power.path],
            ),
            patch(
                "hhd.plugins.powerbutton.base.evdev.InputDevice",
                return_value=power,
            ),
            patch(
                "hhd.plugins.powerbutton.base.mask_power_events",
                side_effect=OSError("unsupported"),
            ),
        ):
            devices = reconcile_power_devices({}, ignored_paths)

        self.assertEqual(devices, {})
        self.assertEqual(ignored_paths, {power.path})
        self.assertTrue(power.closed)

    def test_list_failure_preserves_existing_devices(self):
        power = FakeDevice("/dev/input/event1", name="Power Button")
        devices = {power.path: power}
        with patch(
            "hhd.plugins.powerbutton.base.evdev.list_devices",
            side_effect=OSError("unavailable"),
        ):
            self.assertIs(reconcile_power_devices(devices), devices)
        self.assertFalse(power.closed)

    def test_close_tolerates_device_errors(self):
        device = FakeDevice("/dev/input/event1", name="Power Button")
        device.close = MagicMock(side_effect=OSError("gone"))
        devices = {device.path: device}
        close_power_devices(devices)
        self.assertEqual(devices, {})

    def test_dead_device_is_quarantined_until_path_disappears(self):
        power = FakeDevice("/dev/input/event1", name="Power Button")
        devices = {power.path: power}
        ignored_paths = set()

        quarantine_power_device(devices, ignored_paths, power.path)

        self.assertEqual(devices, {})
        self.assertEqual(ignored_paths, {power.path})
        self.assertTrue(power.closed)

        with patch("hhd.plugins.powerbutton.base.evdev.list_devices", return_value=[]):
            reconcile_power_devices(devices, ignored_paths)
        self.assertEqual(ignored_paths, set())


class PowerEventStateTest(unittest.TestCase):
    key_down = input_event(B("EV_KEY"), B("KEY_POWER"), 1)
    key_repeat = input_event(B("EV_KEY"), B("KEY_POWER"), 2)
    key_up = input_event(B("EV_KEY"), B("KEY_POWER"), 0)
    lid_close = input_event(B("EV_SW"), B("SW_LID"), 1)
    lid_open = input_event(B("EV_SW"), B("SW_LID"), 0)

    def test_short_press_dispatches_on_release(self):
        state = PowerEventState()
        self.assertIsNone(state.handle(self.key_down, 10.0))
        self.assertEqual(state.handle(self.key_up, 10.5), "short")

    def test_long_press_dispatches_at_timeout_once(self):
        state = PowerEventState()
        state.handle(self.key_down, 10.0)
        self.assertIsNone(state.timeout(10.0 + LONG_PRESS_DELAY - 0.01))
        self.assertEqual(state.timeout(10.0 + LONG_PRESS_DELAY), "long")
        self.assertIsNone(state.timeout(20.0))
        self.assertIsNone(state.handle(self.key_up, 20.0))

    def test_long_press_can_dispatch_on_release(self):
        state = PowerEventState()
        state.handle(self.key_down, 10.0)
        self.assertEqual(state.handle(self.key_up, 10.0 + LONG_PRESS_DELAY), "long")

    def test_repeats_are_ignored(self):
        state = PowerEventState()
        self.assertIsNone(state.handle(self.key_repeat, 10.0))
        self.assertIsNone(state.handle(self.key_up, 11.0))

    def test_lid_close_is_short_and_lid_open_is_ignored(self):
        state = PowerEventState()
        self.assertIsNone(state.handle(self.lid_open, 10.0))
        self.assertEqual(state.handle(self.lid_close, 10.0), "short")

    def test_duplicate_sources_are_debounced(self):
        state = PowerEventState()
        state.handle(self.key_down, 10.0)
        self.assertEqual(state.handle(self.key_up, 10.1), "short")
        self.assertIsNone(state.handle(self.key_down, 10.2))
        self.assertIsNone(state.handle(self.key_up, 10.3))
        self.assertIsNone(state.handle(self.lid_close, 10.5))
        self.assertEqual(
            state.handle(self.lid_close, 10.1 + DEBOUNCE_DELAY + 0.01),
            "short",
        )

    def test_events_queued_during_sleep_are_suppressed(self):
        state = PowerEventState()
        state.begin_cycle(10.0)
        state.handle(self.key_down, 10.1)
        state.begin_cycle(20.0)

        self.assertIsNone(state.handle(self.key_down, 20.0))
        self.assertIsNone(state.handle(self.key_up, 20.1))
        self.assertIsNone(state.handle(self.lid_close, 20.2))
        self.assertEqual(state.handle(self.lid_close, 21.01), "short")

    def test_poll_timeout_tracks_long_press_deadline(self):
        state = PowerEventState()
        self.assertEqual(state.poll_timeout(10.0), 0.5)
        state.handle(self.key_down, 10.0)
        self.assertEqual(state.poll_timeout(11.75), 0.25)
        self.assertEqual(state.poll_timeout(12.1), 0.0)


class EvdevMaskTest(unittest.TestCase):
    def test_set_evdev_mask_builds_expected_bitmap(self):
        captured = None

        def inspect_ioctl(fd, request, data):
            nonlocal captured
            event_type, size, pointer = struct.unpack("=IIQ", data)
            captured = (
                fd,
                request,
                event_type,
                ctypes.string_at(pointer, size),
            )

        with patch("hhd.plugins.powerbutton.base.ioctl", side_effect=inspect_ioctl):
            set_evdev_mask(42, B("EV_KEY"), [B("KEY_POWER")])

        self.assertIsNotNone(captured)
        fd, request, event_type, mask = captured
        self.assertEqual((fd, request, event_type), (42, EVIOCSMASK, B("EV_KEY")))
        self.assertGreaterEqual(len(mask), 8)
        self.assertEqual(len(mask) % 8, 0)
        self.assertEqual(mask[B("KEY_POWER") >> 3], 1 << (B("KEY_POWER") & 7))
        self.assertEqual(sum(byte.bit_count() for byte in mask), 1)

    def test_event_type_mask_allows_only_key_and_switch_events(self):
        captured = None

        def inspect_ioctl(fd, request, data):
            nonlocal captured
            _, size, pointer = struct.unpack("=IIQ", data)
            captured = ctypes.string_at(pointer, size)

        with patch("hhd.plugins.powerbutton.base.ioctl", side_effect=inspect_ioctl):
            set_evdev_mask(
                42,
                B("EV_SYN"),
                [B("EV_KEY"), B("EV_SW")],
            )

        self.assertIsNotNone(captured)
        self.assertEqual(
            captured[0],
            (1 << B("EV_KEY")) | (1 << B("EV_SW")),
        )
        self.assertEqual(sum(byte.bit_count() for byte in captured), 2)

    def test_power_mask_is_independent_of_advertised_capabilities(self):
        device = FakeDevice(
            "/dev/input/event1",
            capabilities={B("EV_REL"): [0, 1]},
        )

        with patch("hhd.plugins.powerbutton.base.set_evdev_mask") as set_mask:
            mask_power_events(device)

        set_mask.assert_any_call(device.fd, B("EV_SYN"), (B("EV_KEY"), B("EV_SW")))
        set_mask.assert_any_call(device.fd, B("EV_KEY"), (B("KEY_POWER"),))
        set_mask.assert_any_call(device.fd, B("EV_SW"), (B("SW_LID"),))
        self.assertEqual(set_mask.call_count, 3)


class LogindInhibitorTest(unittest.TestCase):
    def test_acquires_exact_inhibitor_and_closes_fd(self):
        returned_fd = MagicMock()
        returned_fd.take.return_value = 42
        inhibit = MagicMock(return_value=returned_fd)
        manager = MagicMock()
        manager.get_dbus_method.return_value = inhibit
        bus = MagicMock()
        bus.get_object.return_value = manager
        inhibitor = LogindInhibitor()

        with (
            patch("dbus.SystemBus", return_value=bus),
            patch("hhd.plugins.powerbutton.base.os.close") as close,
        ):
            self.assertTrue(inhibitor.acquire())
            self.assertTrue(inhibitor.active)
            inhibitor.release()

        bus.get_object.assert_called_once_with(LOGIN1_BUS, LOGIN1_PATH)
        manager.get_dbus_method.assert_called_once_with("Inhibit", LOGIN1_INTERFACE)
        inhibit.assert_called_once_with(
            INHIBIT_WHAT,
            "HandheldDaemon",
            "Handheld Daemon handles power and lid events",
            "block",
        )
        close.assert_called_once_with(42)
        self.assertFalse(inhibitor.active)

    def test_acquire_failure_leaves_inhibitor_inactive(self):
        inhibitor = LogindInhibitor()
        with patch("dbus.SystemBus", side_effect=RuntimeError("no bus")):
            self.assertFalse(inhibitor.acquire())
        self.assertFalse(inhibitor.active)

    def test_missing_dbus_module_leaves_inhibitor_inactive(self):
        inhibitor = LogindInhibitor()
        with patch.dict(sys.modules, {"dbus": None}):
            self.assertFalse(inhibitor.acquire())
        self.assertFalse(inhibitor.active)


class HandlerLifecycleTest(unittest.TestCase):
    def test_inhibitor_failure_does_not_process_events(self):
        should_exit = MagicMock()
        should_exit.is_set.side_effect = [False, True]
        device = FakeDevice("/dev/input/event1", name="Power Button")
        inhibitor = MagicMock()
        inhibitor.active = False
        inhibitor.acquire.return_value = False

        def reconcile(devices, ignored_paths):
            devices[device.path] = device
            return devices

        with (
            patch(
                "hhd.plugins.powerbutton.base.is_steam_gamepad_running",
                return_value=True,
            ),
            patch(
                "hhd.plugins.powerbutton.base.reconcile_power_devices",
                side_effect=reconcile,
            ),
            patch(
                "hhd.plugins.powerbutton.base.LogindInhibitor",
                return_value=inhibitor,
            ),
            patch("hhd.plugins.powerbutton.base.execute_power_action") as execute,
        ):
            power_button_run(should_exit, MagicMock())

        inhibitor.acquire.assert_called_once_with()
        execute.assert_not_called()
        self.assertTrue(device.closed)

    def test_plugin_start_and_stop_manage_worker(self):
        worker = MagicMock()
        plugin = PowerbuttondPlugin()
        plugin.emit = MagicMock()

        with patch("hhd.plugins.powerbutton.Thread", return_value=worker) as thread:
            plugin.start()
            self.assertTrue(plugin.started)
            thread.assert_called_once()
            worker.start.assert_called_once_with()
            plugin.stop()

        worker.join.assert_called_once_with()
        self.assertFalse(plugin.started)
        self.assertIsNone(plugin.event)
        self.assertIsNone(plugin.t)

    def test_steam_exit_releases_inhibitor_and_devices(self):
        should_exit = MagicMock()
        should_exit.is_set.side_effect = [False, False, True]
        device = FakeDevice("/dev/input/event1", name="Power Button")

        class FakeInhibitor:
            def __init__(self):
                self.active = False
                self.acquired = 0
                self.released = 0

            def acquire(self):
                self.acquired += 1
                self.active = True
                return True

            def release(self):
                self.released += 1
                self.active = False

        inhibitor = FakeInhibitor()

        def reconcile(devices, ignored_paths):
            devices[device.path] = device
            return devices

        with (
            patch(
                "hhd.plugins.powerbutton.base.is_steam_gamepad_running",
                side_effect=[True, False],
            ),
            patch(
                "hhd.plugins.powerbutton.base.reconcile_power_devices",
                side_effect=reconcile,
            ),
            patch(
                "hhd.plugins.powerbutton.base.LogindInhibitor",
                return_value=inhibitor,
            ),
            patch(
                "hhd.plugins.powerbutton.base.select.select", return_value=([], [], [])
            ),
        ):
            power_button_run(should_exit, MagicMock())

        self.assertEqual(inhibitor.acquired, 1)
        self.assertGreaterEqual(inhibitor.released, 1)
        self.assertTrue(device.closed)

    def test_autodetect_is_generic_and_preserves_existing_plugin(self):
        detected = autodetect([])
        self.assertEqual(len(detected), 1)
        self.assertIsInstance(detected[0], PowerbuttondPlugin)
        existing = [MagicMock()]
        self.assertIs(autodetect(existing), existing)


if __name__ == "__main__":
    unittest.main()
