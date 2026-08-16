import ctypes
import unittest
from unittest.mock import MagicMock, patch

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
    CEC_MSG_ACTIVE_SOURCE,
    CEC_MSG_GIVE_DEVICE_POWER_STATUS,
    CEC_MSG_IMAGE_VIEW_ON,
    CEC_MSG_INACTIVE_SOURCE,
    CEC_MSG_REPORT_PHYSICAL_ADDR,
    CEC_MSG_REPORT_POWER_STATUS,
    CEC_MSG_REQUEST_ACTIVE_SOURCE,
    CEC_MSG_SET_OSD_NAME,
    CEC_MSG_STANDBY,
    CEC_OP_ALL_DEVTYPE_PLAYBACK,
    CEC_OP_POWER_STATUS_STANDBY,
    CEC_OP_PRIM_DEVTYPE_PLAYBACK,
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

        def fake_ioctl(fd, request, value):
            nonlocal configured
            if request == CEC_ADAP_G_CAPS:
                value.capabilities = CEC_CAP_LOG_ADDRS | CEC_CAP_TRANSMIT
                value.available_log_addrs = 1
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
                    value.rx_status = 1
                    value.len = 4
                    value.msg[1] = CEC_MSG_ACTIVE_SOURCE
                    value.msg[2] = reported_active >> 8
                    value.msg[3] = reported_active & 0xFF
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


class CecServiceTest(unittest.TestCase):
    def test_scans_for_adapters_after_worker_start(self):
        service = CecService(MagicMock())
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
