import unittest
from unittest.mock import MagicMock, mock_open, patch

from hhd.plugins.plugin import get_flatpak_instance, run_steam_command


class FlatpakInstanceTest(unittest.TestCase):
    def test_reads_matching_numeric_instance(self):
        contents = """\
[Application]
name=org.anatase.Steam

[Instance]
instance-id=4110101546
"""
        with patch("builtins.open", mock_open(read_data=contents)) as opened:
            instance = get_flatpak_instance(1234, "org.anatase.Steam")

        self.assertEqual(instance, "4110101546")
        opened.assert_called_once_with("/proc/1234/root/.flatpak-info")

    def test_rejects_another_application(self):
        contents = """\
[Application]
name=org.example.Other

[Instance]
instance-id=4110101546
"""
        with patch("builtins.open", mock_open(read_data=contents)):
            instance = get_flatpak_instance(1234, "org.anatase.Steam")

        self.assertIsNone(instance)

    def test_rejects_non_numeric_instance(self):
        contents = """\
[Application]
name=org.anatase.Steam

[Instance]
instance-id=org.anatase.Steam
"""
        with patch("builtins.open", mock_open(read_data=contents)):
            instance = get_flatpak_instance(1234, "org.anatase.Steam")

        self.assertIsNone(instance)


class RunSteamCommandTest(unittest.TestCase):
    @patch("hhd.plugins.plugin.get_user_systemd_environment")
    @patch("hhd.plugins.plugin.get_gid", return_value=1000)
    @patch(
        "hhd.plugins.plugin.get_flatpak_instance",
        return_value="4110101546",
    )
    @patch(
        "hhd.plugins.plugin.get_flatpak_id",
        return_value="org.anatase.Steam",
    )
    @patch(
        "hhd.plugins.plugin.get_steam_location",
        return_value=("/home/dev/.steam/root/ubuntu12_32/steam", 4321, 1000),
    )
    @patch("hhd.plugins.plugin.subprocess.run")
    def test_enters_detected_flatpak_instance(
        self,
        run,
        _steam_location,
        _flatpak_id,
        _flatpak_instance,
        _get_gid,
        get_environment,
    ):
        environment = {"XDG_RUNTIME_DIR": "/run/user/1000"}
        get_environment.return_value = environment
        run.return_value = MagicMock(returncode=0)

        self.assertTrue(run_steam_command("steam://shortpowerpress"))

        run.assert_called_once_with(
            [
                "/usr/bin/flatpak",
                "enter",
                "4110101546",
                "/app/bin/steam",
                "-ifrunning",
                "steam://shortpowerpress",
            ],
            check=False,
            user=1000,
            group=1000,
            env=environment,
        )

    @patch("hhd.plugins.plugin.get_gid", return_value=1000)
    @patch("hhd.plugins.plugin.get_flatpak_instance", return_value=None)
    @patch(
        "hhd.plugins.plugin.get_flatpak_id",
        return_value="org.anatase.Steam",
    )
    @patch(
        "hhd.plugins.plugin.get_steam_location",
        return_value=("/home/dev/.steam/root/ubuntu12_32/steam", 4321, 1000),
    )
    @patch("hhd.plugins.plugin.subprocess.run")
    def test_does_not_start_new_flatpak_when_instance_is_missing(
        self,
        run,
        _steam_location,
        _flatpak_id,
        _flatpak_instance,
        _get_gid,
    ):
        self.assertFalse(run_steam_command("steam://shortpowerpress"))
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
