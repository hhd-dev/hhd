import io
import signal
import unittest
from unittest.mock import MagicMock, patch

from gi.repository import Gio

from hhd.plugins import Config
from hhd.plugins.bootc import (
    AUTOMATIC_UPDATE_INTERVALS,
    AUTOMATIC_UPDATE_RETRY,
    BOOTC_CHECK_CMD,
    BOOTC_UPDATE_CMD,
    BootcPlugin,
    FLATPAK_UPDATE_CMD,
)
from hhd.plugins.settings import parse_defaults


class BootcFlatpakTest(unittest.TestCase):
    def setUp(self):
        self.plugin = BootcPlugin()
        self.conf = Config({})
        self.conf["updates.updates.frequency"] = "never"

    def update_plugin(self):
        with patch.object(self.plugin, "_init"):
            self.plugin.update(self.conf)

    def start_update(self, output: str = ""):
        proc = MagicMock()
        proc.poll.return_value = None
        proc.stdout = io.StringIO(output)
        self.conf["updates.applications.update"] = True

        with patch("hhd.plugins.bootc.subprocess.Popen", return_value=proc) as popen:
            self.update_plugin()

        popen.assert_called_once_with(
            FLATPAK_UPDATE_CMD,
            stdout=-1,
            stderr=-2,
            text=True,
        )
        return proc

    def test_settings_include_applications_when_flatpak_is_available(self):
        with patch("hhd.plugins.bootc.shutil.which", return_value="/usr/bin/flatpak"):
            settings = self.plugin.settings()

        self.assertEqual(
            list(settings["updates"]),
            ["updates", "bootc", "applications"],
        )
        applications = settings["updates"]["applications"]
        self.assertEqual(applications["title"], "Applications")
        self.assertEqual(
            set(applications["children"]),
            {"update", "progress", "status", "error"},
        )

    def test_settings_hide_applications_when_flatpak_is_unavailable(self):
        with patch("hhd.plugins.bootc.shutil.which", return_value=None):
            settings = self.plugin.settings()

        self.assertNotIn("applications", settings["updates"])

    def test_unified_update_settings_have_expected_defaults(self):
        with patch("hhd.plugins.bootc.shutil.which", return_value="/usr/bin/flatpak"):
            settings = self.plugin.settings()
        updates = settings["updates"]["updates"]
        defaults = Config(parse_defaults(settings))

        self.assertEqual(updates["title"], "Updates")
        self.assertEqual(
            list(updates["children"])[0:2],
            ["update_all", "reboot"],
        )
        self.assertEqual(
            updates["children"]["frequency"]["options"],
            {
                "daily": "Daily",
                "weekly": "Weekly",
                "monthly": "Monthly",
                "never": "Never",
            },
        )
        self.assertIn("expert", updates["children"]["conditions"]["tags"])
        self.assertEqual(defaults["updates.updates.frequency"].conf, "weekly")
        self.assertEqual(defaults["updates.updates.reboot.mode"].conf, "hidden")
        self.assertIs(defaults["updates.updates.conditions.unmetered"].conf, True)
        self.assertIs(defaults["updates.updates.conditions.cpu_load"].conf, True)
        self.assertEqual(defaults["updates.updates.last_attempt"].conf, 0)

    def test_update_starts_once_and_sets_indeterminate_progress(self):
        proc = self.start_update()

        progress = self.conf["updates.applications.progress"].conf
        self.assertEqual(progress["text"], "Updating applications...")
        self.assertIsNone(progress["value"])

        self.conf["updates.applications.update"] = True
        with patch("hhd.plugins.bootc.subprocess.Popen") as popen:
            self.update_plugin()

        popen.assert_not_called()
        self.assertFalse(self.conf.get_action("updates.applications.update"))
        self.assertIs(self.plugin.flatpak_proc, proc)

    def test_success_clears_progress_and_sets_status(self):
        proc = self.start_update("Nothing to do.\n")
        proc.poll.return_value = 0

        self.update_plugin()

        self.assertIsNone(self.conf["updates.applications.progress"].conf)
        self.assertEqual(
            self.conf["updates.applications.status"].conf,
            "Applications are up to date.",
        )
        self.assertIsNone(self.conf["updates.applications.error"].conf)
        self.assertIsNone(self.plugin.flatpak_proc)

    def test_failure_clears_progress_and_sets_error(self):
        proc = self.start_update("Remote failed\n")
        proc.poll.return_value = 2

        self.update_plugin()

        self.assertIsNone(self.conf["updates.applications.progress"].conf)
        self.assertIsNone(self.conf["updates.applications.status"].conf)
        self.assertEqual(
            self.conf["updates.applications.error"].conf,
            "Flatpak update failed with exit code 2.",
        )

    def test_launch_error_is_reported(self):
        self.conf["updates.applications.update"] = True

        with patch(
            "hhd.plugins.bootc.subprocess.Popen",
            side_effect=OSError("flatpak missing"),
        ):
            self.update_plugin()

        self.assertIsNone(self.conf["updates.applications.progress"].conf)
        self.assertEqual(
            self.conf["updates.applications.error"].conf,
            "Failed to start Flatpak update.",
        )

    def test_close_stops_active_update(self):
        proc = self.start_update()

        self.plugin.close()

        proc.send_signal.assert_called_once_with(signal.SIGINT)
        proc.wait.assert_called_once_with()
        self.assertIsNone(self.plugin.flatpak_proc)

    def prepare_scheduled_update(self, frequency: str = "daily"):
        self.plugin.state = "incompatible"
        self.conf["updates.bootc.stage.mode"] = "incompatible"
        self.conf["updates.updates.frequency"] = frequency
        self.conf["updates.updates.last_attempt"] = 0
        self.conf["updates.updates.conditions.unmetered"] = True
        self.conf["updates.updates.conditions.cpu_load"] = True

    def run_scheduled_update(
        self,
        connectivity=Gio.NetworkConnectivity.FULL,
        metered=False,
        cpu_load=0.1,
        uptime=301,
        now=1_000_000,
    ):
        network = MagicMock()
        network.get_network_available.return_value = True
        network.get_connectivity.return_value = connectivity
        network.get_network_metered.return_value = metered
        with (
            patch("hhd.plugins.bootc.time.time", return_value=now),
            patch("hhd.plugins.bootc.get_system_uptime", return_value=uptime),
            patch(
                "gi.repository.Gio.NetworkMonitor.get_default",
                return_value=network,
            ),
            patch(
                "hhd.plugins.bootc.get_normalized_cpu_load",
                return_value=cpu_load,
            ) as get_cpu_load,
        ):
            self.update_plugin()
        return network, get_cpu_load

    def test_automatic_update_requires_more_than_five_minutes_uptime(self):
        self.prepare_scheduled_update()

        with patch("hhd.plugins.bootc.logger.error") as log_error:
            self.run_scheduled_update(uptime=300)

        self.assertEqual(self.conf["updates.updates.last_attempt"].conf, 0)
        log_error.assert_not_called()

    def test_unmet_condition_logs_once_and_retries_after_five_minutes(self):
        self.prepare_scheduled_update()

        with patch("hhd.plugins.bootc.logger.error") as log_error:
            self.run_scheduled_update(metered=True, now=1_000_000)
            self.run_scheduled_update(metered=True, now=1_000_002)
            self.run_scheduled_update(metered=True, now=1_000_299)

        self.assertEqual(AUTOMATIC_UPDATE_RETRY, 300)
        self.assertEqual(self.plugin.next_automatic_update_check, 1_000_300)
        log_error.assert_called_once_with(
            "Automatic update deferred because %s. Retrying in five minutes.",
            "the active network is metered",
        )

    def test_automatic_update_requires_full_internet_before_other_checks(self):
        unavailable = (
            Gio.NetworkConnectivity.LOCAL,
            Gio.NetworkConnectivity.LIMITED,
            Gio.NetworkConnectivity.PORTAL,
        )
        for connectivity in unavailable:
            with self.subTest(connectivity=connectivity):
                self.prepare_scheduled_update()
                self.plugin.next_automatic_update_check = 0

                network, get_cpu_load = self.run_scheduled_update(
                    connectivity=connectivity
                )

                self.assertEqual(self.conf["updates.updates.last_attempt"].conf, 0)
                network.get_network_metered.assert_not_called()
                get_cpu_load.assert_not_called()

        self.prepare_scheduled_update()
        self.plugin.next_automatic_update_check = 0
        network = MagicMock()
        network.get_network_available.return_value = False
        network.get_connectivity.return_value = Gio.NetworkConnectivity.FULL
        with (
            patch("hhd.plugins.bootc.time.time", return_value=1_000_000),
            patch("hhd.plugins.bootc.get_system_uptime", return_value=301),
            patch(
                "gi.repository.Gio.NetworkMonitor.get_default",
                return_value=network,
            ),
            patch("hhd.plugins.bootc.get_normalized_cpu_load") as get_cpu_load,
        ):
            self.update_plugin()

        self.assertEqual(self.conf["updates.updates.last_attempt"].conf, 0)
        network.get_connectivity.assert_not_called()
        network.get_network_metered.assert_not_called()
        get_cpu_load.assert_not_called()

    def test_missing_gio_defers_automatic_update_without_crashing(self):
        self.prepare_scheduled_update()
        real_import = __import__

        def import_without_gio(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "gi.repository" and "Gio" in fromlist:
                raise ImportError("Gio is unavailable")
            return real_import(name, globals, locals, fromlist, level)

        with (
            patch("hhd.plugins.bootc.time.time", return_value=1_000_000),
            patch("hhd.plugins.bootc.get_system_uptime", return_value=301),
            patch("builtins.__import__", side_effect=import_without_gio),
        ):
            self.update_plugin()

        self.assertEqual(self.conf["updates.updates.last_attempt"].conf, 0)

    def test_automatic_update_obeys_metered_and_cpu_conditions(self):
        self.prepare_scheduled_update()
        self.run_scheduled_update(metered=True)
        self.assertEqual(self.conf["updates.updates.last_attempt"].conf, 0)

        self.plugin.next_automatic_update_check = 0
        self.run_scheduled_update(cpu_load=0.2)
        self.assertEqual(self.conf["updates.updates.last_attempt"].conf, 0)

        self.plugin.next_automatic_update_check = 0
        self.run_scheduled_update(cpu_load=0.199)
        self.assertEqual(self.conf["updates.updates.last_attempt"].conf, 1_000_000)

    def test_disabled_optional_conditions_are_bypassed(self):
        self.prepare_scheduled_update()
        self.conf["updates.updates.conditions.unmetered"] = False
        self.conf["updates.updates.conditions.cpu_load"] = False

        network, get_cpu_load = self.run_scheduled_update(metered=True, cpu_load=1)

        self.assertEqual(self.conf["updates.updates.last_attempt"].conf, 1_000_000)
        network.get_network_metered.assert_not_called()
        get_cpu_load.assert_not_called()

    def test_frequency_intervals_and_never(self):
        now = 4_000_000
        for frequency, interval in AUTOMATIC_UPDATE_INTERVALS.items():
            with self.subTest(frequency=frequency):
                self.prepare_scheduled_update(frequency)
                self.conf["updates.updates.last_attempt"] = now - interval + 1
                self.plugin.next_automatic_update_check = 0
                self.run_scheduled_update(now=now)
                self.assertEqual(
                    self.conf["updates.updates.last_attempt"].conf,
                    now - interval + 1,
                )

                self.plugin.next_automatic_update_check = 0
                self.conf["updates.updates.last_attempt"] = now - interval
                self.run_scheduled_update(now=now)
                self.assertEqual(
                    self.conf["updates.updates.last_attempt"].conf,
                    now,
                )

        self.prepare_scheduled_update("never")
        self.plugin.next_automatic_update_check = 0
        self.run_scheduled_update(now=now)
        self.assertEqual(self.conf["updates.updates.last_attempt"].conf, 0)

    def test_update_all_ignores_conditions_and_starts_both_updates(self):
        flatpak_proc = MagicMock()
        flatpak_proc.poll.return_value = None
        flatpak_proc.stdout = io.StringIO("")
        bootc_proc = MagicMock()
        bootc_proc.poll.return_value = None
        self.plugin.state = "ready_check"
        self.conf["updates.bootc.stage.mode"] = "ready_check"
        self.conf["updates.applications.update"] = False
        self.conf["updates.updates.update_all"] = True

        with (
            patch("hhd.plugins.bootc.time.time", return_value=1_000_000),
            patch(
                "gi.repository.Gio.NetworkMonitor.get_default",
                side_effect=AssertionError("manual updates must not check networking"),
            ),
            patch("hhd.plugins.bootc.subprocess.Popen", return_value=flatpak_proc),
            patch(
                "hhd.plugins.bootc.run_command_threaded",
                return_value=bootc_proc,
            ) as run_bootc,
        ):
            self.update_plugin()

        run_bootc.assert_called_once_with(BOOTC_CHECK_CMD)
        self.assertEqual(self.conf["updates.updates.last_attempt"].conf, 1_000_000)
        self.assertTrue(self.plugin.update_all_pending)
        self.assertIs(self.plugin.flatpak_proc, flatpak_proc)

    def test_update_all_stages_bootc_after_check_finds_update(self):
        check_proc = MagicMock()
        check_proc.poll.return_value = None
        update_proc = MagicMock()
        update_proc.poll.return_value = None
        self.plugin.state = "ready_check"
        self.conf["updates.bootc.stage.mode"] = "ready_check"
        self.conf["updates.updates.update_all"] = True

        with patch(
            "hhd.plugins.bootc.run_command_threaded", return_value=check_proc
        ) as run_bootc:
            self.update_plugin()

        run_bootc.assert_called_once_with(BOOTC_CHECK_CMD)
        self.assertTrue(self.plugin.update_all_pending)

        self.plugin.proc = None
        self.plugin.state = "ready"
        self.plugin.bootc_progress = False
        self.conf["updates.bootc.stage.mode"] = "ready"
        with patch(
            "hhd.plugins.bootc.run_command_threaded", return_value=update_proc
        ) as run_bootc:
            self.update_plugin()

        run_bootc.assert_called_once_with(BOOTC_UPDATE_CMD)
        self.assertFalse(self.plugin.update_all_pending)

    def test_repeated_update_all_does_not_restart_bootc_check(self):
        check_proc = MagicMock()
        check_proc.poll.return_value = None
        self.plugin.state = "ready_check"
        self.conf["updates.bootc.stage.mode"] = "ready_check"
        self.conf["updates.updates.update_all"] = True

        with patch(
            "hhd.plugins.bootc.run_command_threaded", return_value=check_proc
        ) as run_bootc:
            self.update_plugin()
            self.conf["updates.updates.update_all"] = True
            self.update_plugin()

        run_bootc.assert_called_once_with(BOOTC_CHECK_CMD)
        self.assertTrue(self.plugin.checked_update)
        self.assertTrue(self.plugin.update_all_pending)

    def test_update_all_refreshes_an_existing_staged_update(self):
        update_proc = MagicMock()
        update_proc.poll.return_value = None
        self.plugin.state = "ready_updated"
        self.plugin.bootc_progress = False
        self.plugin.update_all_pending = True
        self.conf["updates.bootc.stage.mode"] = "ready_updated"

        with patch(
            "hhd.plugins.bootc.run_command_threaded", return_value=update_proc
        ) as run_bootc:
            self.update_plugin()

        run_bootc.assert_called_once_with(BOOTC_UPDATE_CMD)
        self.assertEqual(self.plugin.state, "loading_cancellable")
        self.assertIs(self.plugin.proc, update_proc)
        self.assertFalse(self.plugin.update_all_pending)
        self.assertEqual(self.conf["updates.updates.reboot.mode"].conf, "hidden")

    def test_reboot_is_shown_after_bootc_is_staged_and_flatpak_finishes(self):
        self.plugin.state = "ready_updated"
        self.conf["updates.bootc.stage.mode"] = "ready_updated"

        self.update_plugin()

        self.assertEqual(self.conf["updates.updates.reboot.mode"].conf, "ready")

    def test_reboot_stays_hidden_while_flatpak_is_updating(self):
        self.plugin.state = "ready_updated"
        self.plugin.flatpak_proc = MagicMock()
        self.plugin.flatpak_proc.poll.return_value = None
        self.conf["updates.bootc.stage.mode"] = "ready_updated"

        self.update_plugin()

        self.assertEqual(self.conf["updates.updates.reboot.mode"].conf, "hidden")

    def test_top_level_reboot_is_gated_by_update_completion(self):
        self.plugin.state = "ready_updated"
        self.conf["updates.bootc.stage.mode"] = "ready_updated"
        self.conf["updates.updates.reboot.ready.reboot"] = True

        with patch("hhd.plugins.bootc.subprocess.run") as run:
            self.update_plugin()

        run.assert_called_once_with(["reboot"])

        self.plugin.state = "ready_check"
        self.conf["updates.bootc.stage.mode"] = "ready_check"
        self.conf["updates.updates.reboot.ready.reboot"] = True
        with patch("hhd.plugins.bootc.subprocess.run") as run:
            self.update_plugin()

        run.assert_not_called()
        self.assertFalse(
            self.conf.get_action("updates.updates.reboot.ready.reboot")
        )

    def test_update_all_skips_bootc_states_requiring_manual_resolution(self):
        for state in ("ready_rebased", "ready_reverted", "incompatible", "unknown"):
            with self.subTest(state=state):
                self.plugin.state = state
                self.plugin.update_all_pending = True
                self.conf["updates.bootc.stage.mode"] = state

                with patch("hhd.plugins.bootc.run_command_threaded") as run_bootc:
                    self.update_plugin()

                run_bootc.assert_not_called()
                self.assertFalse(self.plugin.update_all_pending)

    def test_available_bootc_update_without_version_uses_generic_label(self):
        status = {
            "apiVersion": "org.containers.bootc/v1",
            "spec": {
                "image": {"image": "registry.example/os:stable"},
                "bootOrder": "default",
            },
            "status": {
                "booted": {
                    "image": {"version": "1", "imageDigest": "sha256:1"},
                    "cachedUpdate": {
                        "version": None,
                        "imageDigest": "sha256:2",
                        "image": {"image": "registry.example/os:stable"},
                    },
                },
                "staged": None,
                "rollback": None,
            },
        }

        with patch("hhd.plugins.bootc.get_bootc_status", return_value=status):
            self.plugin._init(self.conf)

        self.assertEqual(self.plugin.state, "ready")
        self.assertEqual(
            self.conf["updates.bootc.update"].conf,
            "Update available",
        )

    def test_positive_check_without_cached_metadata_uses_generic_label(self):
        status = {
            "apiVersion": "org.containers.bootc/v1",
            "spec": {
                "image": {"image": "registry.example/os:stable"},
                "bootOrder": "default",
            },
            "status": {
                "booted": {
                    "image": {"version": "1", "imageDigest": "sha256:1"},
                    "cachedUpdate": None,
                },
                "staged": None,
                "rollback": None,
            },
        }
        proc = MagicMock()
        proc.poll.return_value = 0
        proc.stdout = io.BytesIO(
            b"Update available for "
            b"ostree-image-signed:docker://registry.example/os:stable\n"
        )
        self.plugin.checked_update = True
        self.plugin.state = "loading"
        self.plugin.proc = proc
        self.conf["updates.bootc.stage.mode"] = "loading"

        with patch("hhd.plugins.bootc.get_bootc_status", return_value=status):
            self.plugin.update(self.conf)

        self.assertEqual(self.plugin.state, "ready")
        self.assertIsNone(self.plugin.proc)
        self.assertIs(self.plugin.check_update_available, True)
        self.assertEqual(
            self.conf["updates.bootc.update"].conf,
            "Update available",
        )


if __name__ == "__main__":
    unittest.main()
