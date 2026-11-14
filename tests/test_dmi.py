import importlib
import unittest
from io import StringIO
from unittest.mock import MagicMock, mock_open, patch

from hhd.plugins.utils import read_dmi
from hhd.utils import get_os


class DmiTest(unittest.TestCase):
    def test_missing_and_unreadable_fields_are_empty(self):
        for error in (FileNotFoundError, PermissionError, OSError):
            with self.subTest(error=error), patch("builtins.open", side_effect=error):
                self.assertEqual(read_dmi("product_name"), "")

    def test_identity_is_stripped(self):
        with patch("builtins.open", mock_open(read_data=" ROG Ally RC71L\n")):
            self.assertEqual(read_dmi("product_name"), "ROG Ally RC71L")

    def test_distro_detection_does_not_require_smbios(self):
        with (
            patch.dict("os.environ", {}, clear=True),
            patch("builtins.open", side_effect=FileNotFoundError),
            patch(
                "hhd.utils.platform.freedesktop_os_release",
                return_value={"NAME": "Anatase"},
            ),
            patch("hhd.utils.logger.error") as error,
        ):
            self.assertEqual(get_os(), "anatase")
        error.assert_not_called()

    def test_controller_providers_skip_unavailable_dmi(self):
        providers = [
            importlib.import_module(f"hhd.device.{name}")
            for name in (
                "aura", "ayaneo", "claw", "generic", "gpd.win", "legion_go",
                "orange_pi", "oxp", "rog_ally",
            )
        ]
        for provider in providers:
            for error in (FileNotFoundError, PermissionError):
                with (
                    self.subTest(provider=provider.__name__, error=error),
                    patch("builtins.open", side_effect=error),
                    patch.dict("os.environ", {}, clear=True),
                    patch("hhd.device.aura.enumerate_unique", return_value=[]),
                ):
                    self.assertEqual(provider.autodetect([]), [])

    def test_orange_pi_with_vendor_but_missing_product_is_skipped(self):
        from hhd.device.orange_pi import autodetect

        def read_field(path, *args):
            if path.endswith("/sys_vendor"):
                return StringIO("orangepi")
            raise FileNotFoundError(path)

        with patch("builtins.open", side_effect=read_field):
            self.assertEqual(autodetect([]), [])

    def test_missing_dmi_preserves_usb_aura_detection(self):
        from hhd.device.aura import XGM_PID, autodetect

        with (
            patch("builtins.open", side_effect=FileNotFoundError),
            patch(
                "hhd.device.aura.enumerate_unique",
                return_value=[{"product_id": XGM_PID}],
            ),
            patch("hhd.device.aura.AuraPlugin") as plugin,
        ):
            self.assertEqual(autodetect([]), [plugin.return_value])

    def test_missing_dmi_preserves_forced_claw_detection(self):
        from hhd.device.claw import CONFS, autodetect

        with (
            patch("builtins.open", side_effect=FileNotFoundError),
            patch.dict("os.environ", {"HHD_FORCE_CLAW": "1"}),
            patch("hhd.device.claw.ClawControllerPlugin") as plugin,
        ):
            self.assertEqual(autodetect([]), [plugin.return_value])
        plugin.assert_called_once_with("forced", CONFS["MS-1T41"])

    def test_adjustor_still_probes_unified_without_dmi(self):
        from adjustor.hhd import autodetect

        def read_field(path, *args):
            if "/dmi/" in path:
                raise FileNotFoundError(path)
            if path == "/proc/cpuinfo":
                return StringIO("CPU architecture: 8\n")
            raise AssertionError(path)

        unified = MagicMock()
        unified.is_supported.return_value = False
        with (
            patch("builtins.open", side_effect=read_field),
            patch.dict("os.environ", {}, clear=True),
            patch("adjustor.hhd.USE_UNIFIED", True),
            patch("adjustor.drivers.unified.UnifiedDriverPlugin", return_value=unified),
        ):
            self.assertEqual(autodetect([]), [])
        unified.is_supported.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
