import ctypes
import errno
import unittest
from unittest.mock import MagicMock, call, patch

from evdev import ecodes

from hhd.plugins import Config
from hhd.plugins.cec import CecPlugin, autodetect
from hhd.plugins.cec.cec import (
    CEC_ADAP_G_CAPS,
    CEC_ADAP_G_PHYS_ADDR,
    CEC_ADAP_S_LOG_ADDRS,
    CEC_CAP_LOG_ADDRS,
    CEC_CAP_TRANSMIT,
    CEC_LOG_ADDR_BROADCAST,
    CEC_LOG_ADDR_TV,
    CEC_LOG_ADDR_TYPE_PLAYBACK,
    CEC_MODE_FOLLOWER,
    CEC_MODE_INITIATOR,
    CEC_MSG_ACTIVE_SOURCE,
    CEC_MSG_GIVE_DEVICE_POWER_STATUS,
    CEC_MSG_IMAGE_VIEW_ON,
    CEC_MSG_INACTIVE_SOURCE,
    CEC_MSG_REPORT_PHYSICAL_ADDR,
    CEC_MSG_REPORT_POWER_STATUS,
    CEC_MSG_REQUEST_ACTIVE_SOURCE,
    CEC_MSG_SET_OSD_NAME,
    CEC_MSG_STANDBY,
    CEC_MSG_USER_CONTROL_PRESSED,
    CEC_MSG_USER_CONTROL_RELEASED,
    CEC_OP_ALL_DEVTYPE_PLAYBACK,
    CEC_OP_POWER_STATUS_STANDBY,
    CEC_OP_PRIM_DEVTYPE_PLAYBACK,
    CEC_OP_UI_CMD_BACK,
    CEC_OP_UI_CMD_DOWN,
    CEC_OP_UI_CMD_ENTER,
    CEC_OP_UI_CMD_LEFT,
    CEC_OP_UI_CMD_RIGHT,
    CEC_OP_UI_CMD_SELECT,
    CEC_OP_UI_CMD_UP,
    CEC_RECEIVE,
    CEC_RX_STATUS_OK,
    CEC_S_MODE,
    CEC_TRANSMIT,
    CEC_TX_STATUS_OK,
    CecCaps,
    CecLogAddrs,
    CecMsg,
    CecState,
    _get_osd_name,
    initialize_cec,
    uninitialize,
)
from hhd.plugins.cec.remote import TvRemote
from hhd.plugins.cec.service import CecService


class CecLayoutTest(unittest.TestCase):
    def test_uapi_layouts_and_ioctl_numbers(self):
        self.assertEqual(ctypes.sizeof(CecCaps), 76)
        self.assertEqual(ctypes.sizeof(CecLogAddrs), 92)
        self.assertEqual(ctypes.sizeof(CecMsg), 56)
        self.assertEqual(CEC_ADAP_G_CAPS, 0xC04C6100)
        self.assertEqual(CEC_ADAP_G_PHYS_ADDR, 0x80026101)
        self.assertEqual(CEC_ADAP_S_LOG_ADDRS, 0xC05C6104)
        self.assertEqual(CEC_TRANSMIT, 0xC0386105)
        self.assertEqual(CEC_RECEIVE, 0xC0386106)
        self.assertEqual(CEC_S_MODE, 0x40046109)

    def test_osd_name_prefers_pretty_name_and_truncates_utf8(self):
        with patch(
            "hhd.plugins.cec.cec.platform.freedesktop_os_release",
            return_value={"PRETTY_NAME": "Bazzité très longue"},
        ):
            name = _get_osd_name()

        self.assertLessEqual(len(name), 14)
        self.assertEqual(name.decode(), "Bazzité très")

    def test_osd_name_falls_back_to_hostname(self):
        with (
            patch(
                "hhd.plugins.cec.cec.platform.freedesktop_os_release",
                return_value={},
            ),
            patch("hhd.plugins.cec.cec.socket.gethostname", return_value="deck"),
        ):
            self.assertEqual(_get_osd_name(), b"deck")

    def test_claims_playback_without_fallback_or_rc_passthrough(self):
        configured = None
        mode = None

        def fake_ioctl(fd, request, value):
            nonlocal configured, mode
            if request == CEC_ADAP_G_CAPS:
                value.capabilities = CEC_CAP_LOG_ADDRS | CEC_CAP_TRANSMIT
                value.available_log_addrs = 1
            elif request == CEC_S_MODE:
                mode = value.value
            elif request == CEC_ADAP_G_PHYS_ADDR:
                value.value = 0x2000
            elif request == CEC_ADAP_S_LOG_ADDRS:
                configured = bytes(value)
                value.log_addr[0] = 4
                value.log_addr_mask = 1 << 4
            return value

        with (
            patch("hhd.plugins.cec.cec.os.open", return_value=10),
            patch("hhd.plugins.cec.cec.os.close"),
            patch("hhd.plugins.cec.cec._ioctl", side_effect=fake_ioctl),
            patch("hhd.plugins.cec.cec._transmit", return_value=None),
            patch("hhd.plugins.cec.cec._get_osd_name", return_value=b"Bazzite"),
        ):
            state = initialize_cec("/dev/cec0")

        self.assertEqual(state.logical_addr, 4)
        self.assertEqual(state.phys_addr, 0x2000)
        self.assertEqual(state.osd_name, b"Bazzite")
        self.assertEqual(mode, CEC_MODE_INITIATOR | CEC_MODE_FOLLOWER)
        self.assertIsNotNone(configured)
        laddrs = CecLogAddrs.from_buffer_copy(configured)
        self.assertEqual(laddrs.flags, 0)
        self.assertEqual(laddrs.primary_device_type[0], CEC_OP_PRIM_DEVTYPE_PLAYBACK)
        self.assertEqual(laddrs.log_addr_type[0], CEC_LOG_ADDR_TYPE_PLAYBACK)
        self.assertEqual(laddrs.all_device_types[0], CEC_OP_ALL_DEVTYPE_PLAYBACK)


class CecBehaviorTest(unittest.TestCase):
    _DEFAULT_ACTIVE = object()

    def fake_bus(
        self,
        power=None,
        active=None,
        fail=(),
        cleanup_active=_DEFAULT_ACTIVE,
    ):
        messages = []
        self.frames = []
        current_active = active
        active_queries = 0
        pending_active = []

        def fake_ioctl(fd, request, value):
            nonlocal active_queries, current_active
            if request == CEC_ADAP_G_CAPS:
                value.capabilities = CEC_CAP_LOG_ADDRS | CEC_CAP_TRANSMIT
                value.available_log_addrs = 1
                return value
            if request == CEC_ADAP_G_PHYS_ADDR:
                value.value = 0x2000
                return value
            if request == CEC_ADAP_S_LOG_ADDRS:
                if value.num_log_addrs:
                    value.log_addr[0] = 4
                    value.log_addr_mask = 1 << 4
                return value
            if request == CEC_RECEIVE:
                if not pending_active:
                    raise OSError(errno.EAGAIN, "no CEC message")
                reported_active = pending_active.pop(0)
                value.rx_status = CEC_RX_STATUS_OK
                value.len = 4
                value.msg[0] = 0x4F
                value.msg[1] = CEC_MSG_ACTIVE_SOURCE
                value.msg[2] = reported_active >> 8
                value.msg[3] = reported_active & 0xFF
                return value
            if request != CEC_TRANSMIT:
                return value
            opcode = int(value.msg[1])
            messages.append(opcode)
            self.frames.append(
                (
                    int(value.msg[0]) & 0xF,
                    opcode,
                    tuple(int(v) for v in value.msg[2 : value.len]),
                )
            )
            if opcode in fail:
                value.tx_status = 0
                return value
            value.tx_status = CEC_TX_STATUS_OK
            if opcode == CEC_MSG_GIVE_DEVICE_POWER_STATUS and power is not None:
                value.rx_status = 1
                value.len = 3
                value.msg[1] = CEC_MSG_REPORT_POWER_STATUS
                value.msg[2] = power
            elif opcode == CEC_MSG_REQUEST_ACTIVE_SOURCE:
                active_queries += 1
                reported_active = current_active
                if active_queries > 1 and cleanup_active is not self._DEFAULT_ACTIVE:
                    reported_active = cleanup_active
                if reported_active is not None:
                    pending_active.append(reported_active)
            elif opcode == CEC_MSG_ACTIVE_SOURCE:
                current_active = (int(value.msg[2]) << 8) | int(value.msg[3])
            return value

        return messages, fake_ioctl

    def lifecycle(self, bus):
        with (
            patch("hhd.plugins.cec.cec.os.open", return_value=10),
            patch("hhd.plugins.cec.cec.os.close"),
            patch("hhd.plugins.cec.cec._ioctl", side_effect=bus),
            patch("hhd.plugins.cec.cec._get_osd_name", return_value=b"Anatase"),
            patch("hhd.plugins.cec.cec.select.select", return_value=([10], [], [])),
        ):
            state = initialize_cec("/dev/cec0")
            uninitialize(state)
        return state

    def test_identifies_playback_device_on_its_physical_input(self):
        _, bus = self.fake_bus(power=0, active=0x2000)
        self.lifecycle(bus)

        self.assertIn(
            (
                CEC_LOG_ADDR_BROADCAST,
                CEC_MSG_REPORT_PHYSICAL_ADDR,
                (0x20, 0x00, CEC_OP_PRIM_DEVTYPE_PLAYBACK),
            ),
            self.frames,
        )
        self.assertIn(
            (CEC_LOG_ADDR_TV, CEC_MSG_SET_OSD_NAME, tuple(b"Anatase")),
            self.frames,
        )

    def test_off_tv_activation_and_restoration_order(self):
        messages, bus = self.fake_bus(power=CEC_OP_POWER_STATUS_STANDBY, active=0x1000)
        state = self.lifecycle(bus)

        self.assertEqual(
            messages,
            [
                CEC_MSG_GIVE_DEVICE_POWER_STATUS,
                CEC_MSG_IMAGE_VIEW_ON,
                CEC_MSG_REPORT_PHYSICAL_ADDR,
                CEC_MSG_SET_OSD_NAME,
                CEC_MSG_REQUEST_ACTIVE_SOURCE,
                CEC_MSG_ACTIVE_SOURCE,
                CEC_MSG_REQUEST_ACTIVE_SOURCE,
                CEC_MSG_INACTIVE_SOURCE,
                CEC_MSG_STANDBY,
            ],
        )
        self.assertTrue(state.powered_by_hhd)
        self.assertTrue(state.announced_active)

    def test_already_active_source_is_not_announced_or_undone(self):
        messages, bus = self.fake_bus(power=0, active=0x2000)
        self.lifecycle(bus)

        self.assertEqual(
            messages,
            [
                CEC_MSG_GIVE_DEVICE_POWER_STATUS,
                CEC_MSG_REPORT_PHYSICAL_ADDR,
                CEC_MSG_SET_OSD_NAME,
                CEC_MSG_REQUEST_ACTIVE_SOURCE,
            ],
        )

    def test_missing_active_source_uses_active_and_inactive(self):
        messages, bus = self.fake_bus(power=0, active=None)
        self.lifecycle(bus)

        self.assertEqual(
            messages,
            [
                CEC_MSG_GIVE_DEVICE_POWER_STATUS,
                CEC_MSG_REPORT_PHYSICAL_ADDR,
                CEC_MSG_SET_OSD_NAME,
                CEC_MSG_REQUEST_ACTIVE_SOURCE,
                CEC_MSG_ACTIVE_SOURCE,
                CEC_MSG_INACTIVE_SOURCE,
            ],
        )

    def test_unknown_power_is_never_turned_off(self):
        messages, bus = self.fake_bus(power=None, active=0x1000)
        self.lifecycle(bus)

        self.assertNotIn(CEC_MSG_IMAGE_VIEW_ON, messages)
        self.assertNotIn(CEC_MSG_STANDBY, messages)

    def test_failed_wakeup_is_not_owned(self):
        messages, bus = self.fake_bus(
            power=CEC_OP_POWER_STATUS_STANDBY,
            active=0x1000,
            fail=(CEC_MSG_IMAGE_VIEW_ON,),
        )
        state = self.lifecycle(bus)

        self.assertFalse(state.powered_by_hhd)
        self.assertNotIn(CEC_MSG_STANDBY, messages)

    def test_powered_tv_stays_on_if_active_announcement_fails(self):
        messages, bus = self.fake_bus(
            power=CEC_OP_POWER_STATUS_STANDBY,
            active=0x1000,
            fail=(CEC_MSG_ACTIVE_SOURCE,),
        )
        state = self.lifecycle(bus)

        self.assertTrue(state.powered_by_hhd)
        self.assertFalse(state.announced_active)
        self.assertEqual(
            messages[-2:], [CEC_MSG_REQUEST_ACTIVE_SOURCE, CEC_MSG_INACTIVE_SOURCE]
        )
        self.assertNotIn(CEC_MSG_STANDBY, messages)

    def test_powered_tv_stays_on_if_another_source_became_active(self):
        messages, bus = self.fake_bus(
            power=CEC_OP_POWER_STATUS_STANDBY,
            active=0x1000,
            cleanup_active=0x3000,
        )
        state = self.lifecycle(bus)

        self.assertTrue(state.powered_by_hhd)
        self.assertNotIn(CEC_MSG_STANDBY, messages)
        self.assertEqual(
            messages[-2:], [CEC_MSG_REQUEST_ACTIVE_SOURCE, CEC_MSG_INACTIVE_SOURCE]
        )

    def test_missing_active_reply_uses_last_known_active_state(self):
        messages, bus = self.fake_bus(
            power=CEC_OP_POWER_STATUS_STANDBY,
            active=0x1000,
            cleanup_active=None,
        )
        state = self.lifecycle(bus)

        self.assertTrue(state.powered_by_hhd)
        self.assertEqual(
            messages[-3:],
            [
                CEC_MSG_REQUEST_ACTIVE_SOURCE,
                CEC_MSG_INACTIVE_SOURCE,
                CEC_MSG_STANDBY,
            ],
        )


def remote_msg(opcode, command=None, destination=4):
    msg = CecMsg()
    msg.len = 2 if command is None else 3
    msg.msg[0] = destination
    msg.msg[1] = opcode
    if command is not None:
        msg.msg[2] = command
    return msg


class TvRemoteTest(unittest.TestCase):
    def open_remote(self):
        emit = MagicMock()
        uinput = MagicMock()
        patcher = patch("hhd.plugins.cec.remote.UInput", return_value=uinput)
        patched = patcher.start()
        self.addCleanup(patcher.stop)
        remote = TvRemote(emit)
        remote.open()
        return remote, emit, uinput, patched

    def test_creates_keyboard_named_tv_remote(self):
        _, _, _, uinput_type = self.open_remote()

        uinput_type.assert_called_once_with(
            {
                ecodes.EV_KEY: [
                    ecodes.KEY_ESC,
                    ecodes.KEY_ENTER,
                    ecodes.KEY_UP,
                    ecodes.KEY_LEFT,
                    ecodes.KEY_RIGHT,
                    ecodes.KEY_DOWN,
                ]
            },
            name="Handheld Daemon TV Remote",
            phys="phys-hhd-cec",
        )

    def test_ok_and_arrows_are_keyboard_keys_with_repeat(self):
        remote, _, uinput, _ = self.open_remote()
        mappings = (
            (CEC_OP_UI_CMD_SELECT, ecodes.KEY_ENTER),
            (CEC_OP_UI_CMD_ENTER, ecodes.KEY_ENTER),
            (CEC_OP_UI_CMD_UP, ecodes.KEY_UP),
            (CEC_OP_UI_CMD_DOWN, ecodes.KEY_DOWN),
            (CEC_OP_UI_CMD_LEFT, ecodes.KEY_LEFT),
            (CEC_OP_UI_CMD_RIGHT, ecodes.KEY_RIGHT),
        )

        for command, key in mappings:
            remote.handle(remote_msg(CEC_MSG_USER_CONTROL_PRESSED, command), 1)
            remote.handle(remote_msg(CEC_MSG_USER_CONTROL_PRESSED, command), 1.1)
            remote.handle(remote_msg(CEC_MSG_USER_CONTROL_RELEASED), 1.2)
            self.assertEqual(
                uinput.write.call_args_list[-3:],
                [
                    call(ecodes.EV_KEY, key, 1),
                    call(ecodes.EV_KEY, key, 2),
                    call(ecodes.EV_KEY, key, 0),
                ],
            )

    def test_back_single_press_is_escape(self):
        remote, emit, uinput, _ = self.open_remote()

        remote.handle(remote_msg(CEC_MSG_USER_CONTROL_PRESSED, CEC_OP_UI_CMD_BACK), 0)
        remote.handle(remote_msg(CEC_MSG_USER_CONTROL_RELEASED), 0.05)
        remote.tick(0.24)
        uinput.write.assert_not_called()
        remote.tick(0.26)

        self.assertEqual(
            uinput.write.call_args_list,
            [
                call(ecodes.EV_KEY, ecodes.KEY_ESC, 1),
                call(ecodes.EV_KEY, ecodes.KEY_ESC, 0),
            ],
        )
        emit.assert_not_called()

    def test_back_double_press_emits_shortcut(self):
        remote, emit, uinput, _ = self.open_remote()

        remote.handle(remote_msg(CEC_MSG_USER_CONTROL_PRESSED, CEC_OP_UI_CMD_BACK), 0)
        remote.handle(remote_msg(CEC_MSG_USER_CONTROL_RELEASED), 0.05)
        remote.handle(
            remote_msg(CEC_MSG_USER_CONTROL_PRESSED, CEC_OP_UI_CMD_BACK), 0.15
        )
        remote.handle(remote_msg(CEC_MSG_USER_CONTROL_RELEASED), 0.2)
        remote.tick(0.41)

        uinput.write.assert_not_called()
        emit.assert_called_once_with({"type": "special", "event": "cec_back_double"})

    def test_back_hold_emits_shortcut_without_escape(self):
        remote, emit, uinput, _ = self.open_remote()

        remote.handle(remote_msg(CEC_MSG_USER_CONTROL_PRESSED, CEC_OP_UI_CMD_BACK), 1)
        remote.tick(1.41)
        remote.handle(remote_msg(CEC_MSG_USER_CONTROL_RELEASED), 1.5)
        remote.tick(2)

        uinput.write.assert_not_called()
        emit.assert_called_once_with({"type": "special", "event": "cec_back_hold"})

    def test_back_triple_press_emits_shortcut(self):
        remote, emit, uinput, _ = self.open_remote()

        for pressed, released in ((0, 0.05), (0.1, 0.15), (0.2, 0.25)):
            remote.handle(
                remote_msg(CEC_MSG_USER_CONTROL_PRESSED, CEC_OP_UI_CMD_BACK),
                pressed,
            )
            remote.handle(remote_msg(CEC_MSG_USER_CONTROL_RELEASED), released)
        remote.tick(0.46)

        uinput.write.assert_not_called()
        emit.assert_called_once_with({"type": "special", "event": "cec_back_triple"})

    def test_late_second_back_press_is_two_single_presses(self):
        remote, emit, uinput, _ = self.open_remote()

        remote.handle(remote_msg(CEC_MSG_USER_CONTROL_PRESSED, CEC_OP_UI_CMD_BACK), 0)
        remote.handle(remote_msg(CEC_MSG_USER_CONTROL_RELEASED), 0.05)
        remote.handle(remote_msg(CEC_MSG_USER_CONTROL_PRESSED, CEC_OP_UI_CMD_BACK), 0.3)
        remote.handle(remote_msg(CEC_MSG_USER_CONTROL_RELEASED), 0.35)
        remote.tick(0.56)

        self.assertEqual(uinput.write.call_count, 4)
        emit.assert_not_called()


class CecServiceTest(unittest.TestCase):
    def test_scans_for_adapters_after_worker_start(self):
        service = CecService(MagicMock())
        service.remote = MagicMock()
        state0 = CecState("/dev/cec0", 10, 0x1000, 4, b"HHD")
        state1 = CecState("/dev/cec1", 11, 0x2000, 8, b"HHD")

        with (
            patch(
                "hhd.plugins.cec.service.glob.glob",
                side_effect=[[], ["/dev/cec0", "/dev/cec1"]],
            ),
            patch(
                "hhd.plugins.cec.service.initialize_cec",
                side_effect=[state0, state1],
            ) as initialize,
        ):
            service.scan()
            self.assertEqual(service.adapters, {})
            service.scan()

        self.assertEqual(set(service.adapters), {"/dev/cec0", "/dev/cec1"})
        self.assertEqual(initialize.call_count, 2)
        service.remote.open.assert_called()

    def test_receives_remote_keys_and_tracks_active_source(self):
        service = CecService(MagicMock())
        service.remote = MagicMock()
        state = CecState("/dev/cec0", 10, 0x2000, 4, b"HHD", active=True)
        service.adapters["/dev/cec0"] = state
        active = remote_msg(CEC_MSG_ACTIVE_SOURCE, destination=CEC_LOG_ADDR_BROADCAST)
        active.len = 4
        active.msg[0] = 0x5F
        active.msg[2] = 0x30
        active.msg[3] = 0
        pressed = remote_msg(CEC_MSG_USER_CONTROL_PRESSED, CEC_OP_UI_CMD_UP)

        with patch(
            "hhd.plugins.cec.service.receive_cec",
            side_effect=[active, pressed, None],
        ):
            service.receive()

        self.assertFalse(state.active)
        service.remote.handle.assert_called_once_with(pressed)

    def test_sleep_uninitializes_adapters_and_reopens_after_resume(self):
        service = CecService(MagicMock())
        state = CecState("/dev/cec0", 10, 0x1000, 4, b"HHD")
        service.adapters["/dev/cec0"] = state
        service.sleep = MagicMock(side_effect=["entry", "exit"])

        with patch("hhd.plugins.cec.service.uninitialize") as uninitialize:
            service._sleep_transition()
        uninitialize.assert_called_once_with(state)
        self.assertTrue(service.suspended)
        service.sleep.inhibit.assert_called_with(False)

        service._sleep_transition()
        self.assertFalse(service.suspended)
        service.sleep.inhibit.assert_called_with(True)

    def test_disappearing_adapter_is_uninitialized(self):
        service = CecService(MagicMock())
        state = CecState("/dev/cec0", 10, 0x1000, 4, b"HHD")
        service.adapters["/dev/cec0"] = state

        with (
            patch("hhd.plugins.cec.service.glob.glob", return_value=[]),
            patch("hhd.plugins.cec.service.uninitialize") as uninitialize,
        ):
            service.scan()

        uninitialize.assert_called_once_with(state)
        self.assertEqual(service.adapters, {})


class CecPluginTest(unittest.TestCase):
    def test_provider_is_only_registered_by_feature_gate(self):
        with patch("hhd.plugins.cec.SUPPORTS_CEC", False):
            self.assertEqual(autodetect([]), [])
        with patch("hhd.plugins.cec.SUPPORTS_CEC", True):
            self.assertIsInstance(autodetect([])[0], CecPlugin)

    def test_setting_is_in_hhd_settings(self):
        setting = CecPlugin().settings()["hhd"]["settings"]["children"]["cec"]
        self.assertTrue(setting["default"])

    def test_tv_remote_shortcuts_have_expected_defaults(self):
        shortcuts = CecPlugin().settings()["shortcuts"]["cec"]

        self.assertEqual(shortcuts["title"], "TV Remote")
        self.assertEqual(shortcuts["children"]["back_double"]["default"], "steam_qam")
        self.assertEqual(shortcuts["children"]["back_hold"]["default"], "hhd_expanded")
        self.assertEqual(
            shortcuts["children"]["back_triple"]["default"], "hhd_expanded"
        )

    def test_worker_only_runs_in_gamemode_when_enabled(self):
        plugin = CecPlugin()
        plugin.start = MagicMock()
        plugin.stop = MagicMock()
        conf = Config({"hhd": {"settings": {"cec": True}}})

        with patch("hhd.plugins.cec.is_steam_gamepad_running", return_value=False):
            plugin.update(conf)
        plugin.start.assert_not_called()

        with patch("hhd.plugins.cec.is_steam_gamepad_running", return_value=True):
            plugin.update(conf)
        plugin.start.assert_called_once()

    def test_worker_stops_on_gamemode_exit_or_setting_disable(self):
        plugin = CecPlugin()
        plugin.thread = MagicMock()
        plugin.stop = MagicMock()

        with patch("hhd.plugins.cec.is_steam_gamepad_running", return_value=False):
            plugin.update(Config({"hhd": {"settings": {"cec": True}}}))
        plugin.stop.assert_called_once()

        plugin.stop.reset_mock()
        with patch("hhd.plugins.cec.is_steam_gamepad_running", return_value=True):
            plugin.update(Config({"hhd": {"settings": {"cec": False}}}))
        plugin.stop.assert_called_once()

    def test_legacy_overlay_sleep_import_uses_shared_handler(self):
        from hhd.plugins.overlay.systemd import WakeHandler as LegacyWakeHandler
        from hhd.plugins.systemd import WakeHandler

        self.assertIs(LegacyWakeHandler, WakeHandler)


if __name__ == "__main__":
    unittest.main()
