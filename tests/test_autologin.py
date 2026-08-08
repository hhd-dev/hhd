import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from hhd.plugins import Config
from hhd.plugins.overlay import OverlayPlugin
from hhd.plugins.overlay.autologin import (
    disable_autologin,
    enable_autologin,
    get_normal_users,
    read_autologin,
    update_autologin,
)


class AutologinConfigTest(unittest.TestCase):
    def test_reads_only_values_at_line_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "plasmalogin.conf")
            with open(path, "w") as f:
                f.write(
                    "# Session=gamemode.desktop\n"
                    " Session=gamemode.desktop\n"
                    "# User=ignored\n"
                    " User=ignored\n"
                )

            self.assertEqual(read_autologin(path), (False, None))

            with open(path, "a") as f:
                f.write("Session=gamemode.desktop\nUser=deck\n")

            self.assertEqual(read_autologin(path), (True, "deck"))

    def test_enable_replaces_stanza_and_preserves_other_sections(self):
        config = (
            "[General]\nTheme=breeze\n\n"
            "[Autologin]\nSession=plasma.desktop\nUser=old\nRemember=true\n\n"
            "[Other]\nValue=1\n"
        )

        updated = enable_autologin(config, "deck")

        self.assertEqual(
            updated,
            "[General]\nTheme=breeze\n\n"
            "[Autologin]\nSession=gamemode.desktop\nUser=deck\n"
            "[Other]\nValue=1\n",
        )

    def test_disable_comments_stanza_in_place(self):
        config = (
            "[General]\nTheme=breeze\n"
            "[Autologin]\nSession=gamemode.desktop\nUser=deck\n\n"
            "[Other]\nValue=1\n"
        )

        self.assertEqual(
            disable_autologin(config),
            "[General]\nTheme=breeze\n"
            "[Autologin]\n# Session=gamemode.desktop\n# User=deck\n# \n"
            "[Other]\nValue=1\n",
        )

    def test_repeated_updates_reuse_stanza_without_backups(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "plasmalogin.conf")
            with open(path, "w") as f:
                f.write("[General]\nTheme=breeze\n")

            update_autologin(True, "deck", path)
            update_autologin(False, "deck", path)
            update_autologin(True, "alice", path)

            with open(path, "r") as f:
                config = f.read()

            self.assertEqual(config.count("[Autologin]"), 1)
            self.assertIn("Session=gamemode.desktop\nUser=alice\n", config)
            self.assertIn("[General]\nTheme=breeze\n", config)
            self.assertEqual(os.listdir(tmp), ["plasmalogin.conf"])


class AutologinUsersTest(unittest.TestCase):
    def test_filters_and_orders_normal_login_users(self):
        with tempfile.TemporaryDirectory() as tmp:
            login_defs = os.path.join(tmp, "login.defs")
            with open(login_defs, "w") as f:
                f.write("UID_MIN 1000\nUID_MAX 2000\n")

            users = [
                SimpleNamespace(pw_uid=1500, pw_name="zoe", pw_shell="/bin/bash"),
                SimpleNamespace(pw_uid=999, pw_name="daemon", pw_shell="/bin/bash"),
                SimpleNamespace(
                    pw_uid=1200, pw_name="service", pw_shell="/sbin/nologin"
                ),
                SimpleNamespace(pw_uid=1000, pw_name="alice", pw_shell="/bin/zsh"),
                SimpleNamespace(pw_uid=2001, pw_name="outside", pw_shell="/bin/bash"),
                SimpleNamespace(pw_uid=1100, pw_name="false", pw_shell="/bin/false"),
            ]

            with patch(
                "hhd.plugins.overlay.autologin.pwd.getpwall", return_value=users
            ):
                self.assertEqual(get_normal_users(login_defs), ["alice", "zoe"])


class AutologinPluginTest(unittest.TestCase):
    def setUp(self):
        self.plugin = OverlayPlugin()
        self.plugin.ovf = MagicMock()

    def settings(self, enabled: bool, users=None, configured=(False, None)):
        if users is None:
            users = ["alice", "deck"]
        with (
            patch("hhd.plugins.overlay.SUPPORTS_AUTOLOGIN", enabled),
            patch("hhd.plugins.overlay.get_normal_users", return_value=users),
            patch("hhd.plugins.overlay.read_autologin", return_value=configured),
            patch(
                "hhd.plugins.overlay.get_touchscreen_quirk", return_value=(False, None)
            ),
            patch("hhd.plugins.overlay.has_touchscreen", return_value=True),
        ):
            return self.plugin.settings()

    def test_settings_are_hidden_without_capability_or_users(self):
        settings = self.settings(False)
        self.assertNotIn("autologin", settings["gamemode"]["gamescope"]["children"])

        settings = self.settings(True, users=[])
        self.assertNotIn("autologin", settings["gamemode"]["gamescope"]["children"])

    def test_settings_expose_detected_mode_and_users(self):
        settings = self.settings(True, configured=(True, "deck"))
        setting = settings["gamemode"]["gamescope"]["children"]["autologin"]

        self.assertEqual(setting["default"], "enabled")
        self.assertEqual(set(setting["modes"]), {"disabled", "enabled"})
        user = setting["modes"]["enabled"]["children"]["user"]
        self.assertEqual(user["title"], "As User")
        self.assertEqual(user["options"], {"alice": "alice", "deck": "deck"})
        self.assertEqual(user["default"], "deck")

    def test_settings_fall_back_to_first_user(self):
        settings = self.settings(True, configured=(True, "missing"))
        user = settings["gamemode"]["gamescope"]["children"]["autologin"]["modes"][
            "enabled"
        ]["children"]["user"]
        self.assertEqual(user["default"], "alice")

    def test_settings_hide_user_field_for_single_user(self):
        settings = self.settings(True, users=["alice"], configured=(False, None))
        enabled = settings["gamemode"]["gamescope"]["children"]["autologin"][
            "modes"
        ]["enabled"]

        self.assertNotIn("user", enabled["children"])

    def test_first_update_synchronizes_without_writing(self):
        self.plugin.autologin_users = ["alice", "deck"]
        conf = Config(
            {
                "gamemode.gamescope.autologin.mode": "enabled",
                "gamemode.gamescope.autologin.enabled.user": "deck",
            }
        )

        with (
            patch("hhd.plugins.overlay.read_autologin", return_value=(False, None)),
            patch("hhd.plugins.overlay.update_autologin") as update,
        ):
            self.plugin._update_autologin(conf)

        update.assert_not_called()
        self.assertEqual(conf.get("gamemode.gamescope.autologin.mode", ""), "disabled")
        self.assertEqual(
            conf.get("gamemode.gamescope.autologin.enabled.user", ""), "alice"
        )

    def test_first_update_preselects_configured_user(self):
        self.plugin.autologin_users = ["alice", "deck"]
        conf = Config({})

        with (
            patch("hhd.plugins.overlay.read_autologin", return_value=(True, "deck")),
            patch("hhd.plugins.overlay.update_autologin") as update,
        ):
            self.plugin._update_autologin(conf)

        update.assert_not_called()
        self.assertEqual(conf.get("gamemode.gamescope.autologin.mode", ""), "enabled")
        self.assertEqual(
            conf.get("gamemode.gamescope.autologin.enabled.user", ""), "deck"
        )

    def test_first_update_does_not_initialize_hidden_single_user_field(self):
        self.plugin.autologin_users = ["alice"]
        conf = Config({})

        with patch(
            "hhd.plugins.overlay.read_autologin", return_value=(False, "alice")
        ):
            self.plugin._update_autologin(conf)

        self.assertNotIn("gamemode.gamescope.autologin.enabled.user", conf)
        self.assertEqual(self.plugin.old_autologin_user, "alice")

    def test_runtime_enable_and_user_change_write(self):
        self.plugin.autologin_users = ["alice", "deck"]
        self.plugin.autologin_initialized = True
        self.plugin.old_autologin_mode = "disabled"
        self.plugin.old_autologin_user = "alice"
        conf = Config(
            {
                "gamemode.gamescope.autologin.mode": "enabled",
                "gamemode.gamescope.autologin.enabled.user": "alice",
            }
        )

        with patch("hhd.plugins.overlay.update_autologin") as update:
            self.plugin._update_autologin(conf)
            conf["gamemode.gamescope.autologin.enabled.user"] = "deck"
            self.plugin._update_autologin(conf)

        self.assertEqual(
            update.call_args_list,
            [unittest.mock.call(True, "alice"), unittest.mock.call(True, "deck")],
        )

    def test_runtime_disable_writes(self):
        self.plugin.autologin_users = ["alice"]
        self.plugin.autologin_initialized = True
        self.plugin.old_autologin_mode = "enabled"
        self.plugin.old_autologin_user = "alice"
        conf = Config(
            {
                "gamemode.gamescope.autologin.mode": "disabled",
                "gamemode.gamescope.autologin.enabled.user": "alice",
            }
        )

        with patch("hhd.plugins.overlay.update_autologin") as update:
            self.plugin._update_autologin(conf)

        update.assert_called_once_with(False, "alice")

    def test_single_user_does_not_read_hidden_user_config(self):
        self.plugin.autologin_users = ["alice"]
        self.plugin.autologin_initialized = True
        self.plugin.old_autologin_mode = "disabled"
        self.plugin.old_autologin_user = "alice"
        conf = Config(
            {
                "gamemode.gamescope.autologin.mode": "enabled",
                "gamemode.gamescope.autologin.enabled.user": "stale",
            }
        )

        with patch("hhd.plugins.overlay.update_autologin") as update:
            self.plugin._update_autologin(conf)

        update.assert_called_once_with(True, "alice")
        self.assertEqual(
            conf.get("gamemode.gamescope.autologin.enabled.user", ""), "stale"
        )

    def test_write_failure_restores_previous_ui_values(self):
        self.plugin.autologin_users = ["alice"]
        self.plugin.autologin_initialized = True
        self.plugin.old_autologin_mode = "disabled"
        self.plugin.old_autologin_user = "alice"
        conf = Config(
            {
                "gamemode.gamescope.autologin.mode": "enabled",
                "gamemode.gamescope.autologin.enabled.user": "alice",
            }
        )

        with patch(
            "hhd.plugins.overlay.update_autologin", side_effect=OSError("read-only")
        ):
            self.plugin._update_autologin(conf)

        self.assertEqual(conf.get("gamemode.gamescope.autologin.mode", ""), "disabled")
        self.assertEqual(
            conf.get("gamemode.gamescope.autologin.enabled.user", ""), "alice"
        )


if __name__ == "__main__":
    unittest.main()
