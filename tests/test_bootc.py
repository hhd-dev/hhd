import io
import signal
import unittest
from unittest.mock import MagicMock, patch

from hhd.plugins import Config
from hhd.plugins.bootc import BootcPlugin, FLATPAK_UPDATE_CMD


class BootcFlatpakTest(unittest.TestCase):
    def setUp(self):
        self.plugin = BootcPlugin()
        self.conf = Config({})

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


if __name__ == "__main__":
    unittest.main()
