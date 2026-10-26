import os
import select
import tempfile
import unittest
from threading import Event
from unittest.mock import MagicMock, patch

from adjustor.drivers.unified import (
    PPData,
    UnifiedDriverPlugin,
    get_profiles,
    profile_worker,
    setup_mode_units,
)
from hhd.plugins import Config
from hhd.plugins.settings import parse_defaults


PROFILES = PPData(
    fn="lenovo-wmi-gamezone",
    pp="platform-profile-0",
    provider="lenovo-wmi-gamezone",
    has_custom=True,
    profiles=(
        ("low-power", "Quiet"),
        ("balanced", "Balanced"),
        ("performance", "Performance"),
        ("custom", "Custom"),
    ),
)


class PlatformProfileWorkerTest(unittest.TestCase):
    def test_emits_tdp_event_when_profile_changes(self):
        should_exit = Event()
        emit = MagicMock()
        profile_file = MagicMock()
        profile_file.__enter__.return_value = profile_file
        profile_file.read.side_effect = ["balanced\n", "performance\n"]
        profile_file.fileno.return_value = 12

        poll = MagicMock()

        def poll_once(_timeout):
            if poll.poll.call_count == 1:
                return [(12, select.POLLPRI)]
            should_exit.set()
            return []

        poll.poll.side_effect = poll_once

        with (
            patch("builtins.open", return_value=profile_file),
            patch("adjustor.drivers.unified.select.poll", return_value=poll),
        ):
            profile_worker(PROFILES, emit, should_exit)

        emit.assert_called_once_with(
            {"type": "platform_profile", "profile": "performance"}
        )
        profile_file.seek.assert_called_once_with(0)


class PlatformProfileUnitsTest(unittest.TestCase):
    def test_quiet_uses_low_power_unit_and_ignores_unknown_modes(self):
        settings = {
            "modes": {
                "quiet": {"type": "container"},
                "balanced": {"type": "container"},
                "custom": {"type": "container", "unit": "kernel"},
                "cool": {"type": "container"},
            }
        }

        setup_mode_units(
            {"low-power": 5, "balanced": 12, "performance": 18},
            settings,
        )

        self.assertEqual(settings["modes"]["quiet"]["unit"], "5W")
        self.assertEqual(settings["modes"]["balanced"]["unit"], "12W")
        self.assertEqual(settings["modes"]["custom"]["unit"], "kernel")
        self.assertNotIn("unit", settings["modes"]["cool"])


class AsusPlatformProfileTest(unittest.TestCase):
    def test_asus_platform_profile_only_exposes_presets(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "platform-profile-0")
            os.mkdir(path)
            with open(os.path.join(path, "name"), "w") as f:
                f.write("asus-wmi\n")
            with open(os.path.join(path, "choices"), "w") as f:
                f.write("quiet balanced performance\n")

            with patch("adjustor.drivers.unified.PP_PATH", root):
                profiles = get_profiles()

        self.assertIsNotNone(profiles)
        assert profiles
        self.assertFalse(profiles.has_custom)
        self.assertEqual(
            tuple(mode for mode, _ in profiles.profiles),
            ("quiet", "balanced", "performance"),
        )


class ThinkPadPlatformProfileTest(unittest.TestCase):
    def test_thinkpad_platform_profile_only_exposes_presets(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "platform-profile-0")
            os.mkdir(path)
            with open(os.path.join(path, "name"), "w") as f:
                f.write("thinkpad-acpi-profile\n")
            with open(os.path.join(path, "choices"), "w") as f:
                f.write("low-power balanced performance\n")

            with patch("adjustor.drivers.unified.PP_PATH", root):
                profiles = get_profiles()

        self.assertIsNotNone(profiles)
        assert profiles
        self.assertEqual(profiles.provider, "thinkpad-acpi-profile")
        self.assertFalse(profiles.has_custom)
        self.assertEqual(
            tuple(mode for mode, _ in profiles.profiles),
            ("low-power", "balanced", "performance"),
        )


class AcerPpdProfileTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = tmp.name
        self.path = os.path.join(root, "platform-profile-0")
        os.mkdir(self.path)
        for name, value in (
            ("name", "acer-wmi"),
            (
                "choices",
                "low-power quiet balanced balanced-performance performance",
            ),
            ("profile", "balanced"),
        ):
            with open(os.path.join(self.path, name), "w") as f:
                f.write(value + "\n")
        pp_path = patch("adjustor.drivers.unified.PP_PATH", root)
        pp_path.start()
        self.addCleanup(pp_path.stop)
        self.plugin = UnifiedDriverPlugin()
        self.plugin.enabled = True
        self.plugin.init = True
        self.plugin.startup = False
        self.plugin.startup_deadline = None
        self.plugin.mode = "balanced"
        self.plugin.emit = MagicMock()
        self.conf = Config(parse_defaults(self.plugin.settings()))
        self.conf["hhd.settings.tdp_enable"] = True
        self.plugin.old_conf = self.conf["tdp.unified"]

    def test_uses_windows_names_and_keeps_eco_instead_of_quiet(self):
        assert self.plugin.profiles
        self.assertFalse(self.plugin.profiles.has_custom)
        self.assertEqual(
            self.plugin.profiles.profiles,
            (
                ("low-power", "Eco"),
                ("balanced", "Balanced"),
                ("balanced-performance", "Performance"),
                ("performance", "Turbo"),
            ),
        )
        settings = self.plugin.settings()["tdp"]["unified"]["children"]["tdp"]
        self.assertNotIn("quiet", settings["modes"])
        self.assertEqual(settings["default"], "balanced")

    def test_ppd_changes_select_eco_balanced_and_performance(self):
        for status, profile in (
            ("power", "low-power"),
            ("balanced", "balanced"),
            ("performance", "balanced-performance"),
        ):
            with self.subTest(status=status):
                self.plugin.emit.reset_mock()
                self.plugin.notify([{"type": "ppd", "status": status}])
                self.plugin.update(self.conf)

                self.assertEqual(self.conf["tdp.unified.tdp.mode"].to(str), profile)
                with open(os.path.join(self.path, "profile")) as f:
                    self.assertEqual(f.read(), profile)
                self.plugin.emit.assert_called_once_with(
                    {"type": "energy", "status": status}
                )

    def test_all_drivers_discover_and_prefer_balanced_performance(self):
        for provider in (
            "amd-dptc",
            "lenovo-wmi-gamezone",
            "asus-wmi",
            "thinkpad-acpi-profile",
            "samsung-galaxybook",
        ):
            with self.subTest(provider=provider):
                with open(os.path.join(self.path, "name"), "w") as f:
                    f.write(provider + "\n")
                self.plugin.profiles = get_profiles()
                assert self.plugin.profiles
                self.assertIn(
                    ("balanced-performance", "Balanced Performance"),
                    self.plugin.profiles.profiles,
                )
                self.plugin.notify([{"type": "ppd", "status": "performance"}])
                self.assertEqual(self.plugin.new_mode, "balanced-performance")

    def test_manual_profiles_publish_the_corresponding_ppd_category(self):
        for profile, status in (
            ("low-power", "power"),
            ("balanced", "balanced"),
            ("balanced-performance", "performance"),
            ("performance", "performance"),
        ):
            with self.subTest(profile=profile):
                self.plugin.old_target = None
                self.plugin.emit.reset_mock()
                self.conf["tdp.unified.tdp.mode"] = profile
                self.plugin.update(self.conf)

                self.plugin.emit.assert_called_once_with(
                    {"type": "energy", "status": status}
                )

    def test_external_performance_profile_uses_supported_notification(self):
        self.plugin.notify(
            [{"type": "platform_profile", "profile": "balanced-performance"}]
        )
        with patch("adjustor.drivers.unified.set_mode") as set_mode:
            self.plugin.update(self.conf)

        self.assertEqual(
            self.conf["tdp.unified.tdp.mode"].to(str), "balanced-performance"
        )
        set_mode.assert_not_called()
        self.plugin.emit.assert_any_call(
            {"type": "special", "event": "tdp_cycle_performance"}
        )
        self.plugin.emit.assert_any_call({"type": "energy", "status": "performance"})


class UnifiedProfileNotificationTest(unittest.TestCase):
    def setUp(self):
        self.plugin = UnifiedDriverPlugin.__new__(UnifiedDriverPlugin)
        self.plugin.profiles = PROFILES
        self.plugin.mode = "balanced"
        self.plugin.system_mode = None
        self.plugin.emit = MagicMock()

    def test_ppd_changes_fall_back_when_balanced_performance_is_unavailable(self):
        for status, profile in (
            ("power", "low-power"),
            ("balanced", "balanced"),
            ("performance", "performance"),
        ):
            with self.subTest(status=status):
                self.plugin.notify([{"type": "ppd", "status": status}])
                self.assertEqual(self.plugin.new_mode, profile)

    def test_external_profile_change_updates_pending_mode_and_notifies(self):
        self.plugin.notify(
            [{"type": "platform_profile", "profile": "performance"}]
        )

        self.assertEqual(self.plugin.system_mode, "performance")
        self.plugin.emit.assert_called_once_with(
            {"type": "special", "event": "tdp_cycle_performance"}
        )

    def test_duplicate_profile_event_is_ignored(self):
        self.plugin.notify([{"type": "platform_profile", "profile": "balanced"}])

        self.assertIsNone(self.plugin.system_mode)
        self.plugin.emit.assert_not_called()

    def test_low_power_uses_quiet_notification(self):
        self.plugin.notify([{"type": "platform_profile", "profile": "low-power"}])

        self.assertEqual(self.plugin.system_mode, "low-power")
        self.plugin.emit.assert_called_once_with(
            {"type": "special", "event": "tdp_cycle_quiet"}
        )

    def test_pending_system_mode_updates_config_without_writing_profile(self):
        conf = Config(
            {
                "hhd": {
                    "settings": {"tdp_enable": True, "tdp_ready": True},
                    "steamos": {},
                },
                "tdp": {
                    "unified": {
                        "tdp": {
                            "mode": "balanced",
                            "custom": {"tdp": 15, "boost": True},
                        },
                        "sys_tdp": "",
                    }
                },
            }
        )
        self.plugin.enabled = True
        self.plugin.initialized = True
        self.plugin.init = True
        self.plugin.failed = False
        self.plugin.has_decky = False
        self.plugin.action_enabled = False
        self.plugin.tdp_set = None
        self.plugin.startup = False
        self.plugin.old_conf = conf["tdp.unified"]
        self.plugin.new_tdp = None
        self.plugin.new_mode = None
        self.plugin.system_mode = "performance"
        self.plugin.tdp = None
        self.plugin.full_fan = None
        self.plugin.fan = None
        self.plugin.queue_tdp = None
        self.plugin.queue_fan = None
        self.plugin.old_target = None
        self.plugin.sys_tdp = False
        self.plugin.startup_deadline = None

        with patch("adjustor.drivers.unified.set_mode") as set_mode:
            self.plugin.update(conf)

        self.assertEqual(conf["tdp.unified.tdp.mode"].to(str), "performance")
        set_mode.assert_not_called()


if __name__ == "__main__":
    unittest.main()
