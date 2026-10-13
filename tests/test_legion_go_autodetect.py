import unittest
from io import StringIO
from unittest.mock import patch

from hhd.device.legion_go import (
    LEGION_GO_CONFS,
    LEGION_S_CONFS,
    LegionGoControllersPlugin,
    LegionGoSControllerPlugin,
    autodetect,
)


class LegionGoAutodetectTest(unittest.TestCase):
    def detect(self, product="INVALID", vendor="LENOVO", bios="N3CN40WW"):
        fields = {
            "product_name": product,
            "sys_vendor": vendor,
            "bios_version": bios,
        }

        def read_field(path):
            name = path.removeprefix("/sys/devices/virtual/dmi/id/")
            value = fields[name]
            if isinstance(value, OSError):
                raise value
            if value is None:
                raise FileNotFoundError(path)
            return StringIO(value)

        with patch("builtins.open", side_effect=read_field) as reader:
            plugins = autodetect([])
        return plugins, reader

    def assert_original_go(self, plugins):
        self.assertEqual(len(plugins), 1)
        self.assertIsInstance(plugins[0], LegionGoControllersPlugin)
        self.assertIs(plugins[0].dconf, LEGION_GO_CONFS["83E1"])

    def test_original_go_bios_versions_with_invalid_product(self):
        for bios in (
            "N3CN26WW",
            "N3CN28WW",
            "N3CN29WW",
            "N3CN29WW_TDP02",
            "N3CN31WW",
            "N3CN35WW",
            "N3CN39WW",
            "N3CN40WW",
        ):
            with self.subTest(bios=bios):
                plugins, _ = self.detect(bios=bios)
                self.assert_original_go(plugins)

    def test_missing_empty_and_unreadable_product(self):
        for product in (None, "", " \n", PermissionError("DMI unavailable")):
            with self.subTest(product=product):
                plugins, _ = self.detect(product=product)
                self.assert_original_go(plugins)

    def test_vendor_and_bios_normalization(self):
        plugins, _ = self.detect(vendor=" lenovo\n", bios=" n3cn40ww\n")
        self.assert_original_go(plugins)

    def test_requires_lenovo_system_vendor(self):
        for vendor in (
            None, "", " \n", "ASUS", "LENOVO OTHER", PermissionError("DMI unavailable")
        ):
            with self.subTest(vendor=vendor):
                plugins, _ = self.detect(vendor=vendor)
                self.assertEqual(plugins, [])

    def test_rejects_missing_unknown_and_other_model_bioses(self):
        for bios in (
            None,
            "",
            " \n",
            PermissionError("DMI unavailable"),
            "UNKNOWN",
            "N3CN",
            "N3CN41WW",
            "N3CN40WW_UNKNOWN",
            "OTHER_N3CN40WW",
            "QCCN16WW",
            "QCCN17WW_Q",
            "GKCN60WW",
            "N0CN17WW",
            "MACN24WW",
            "M1CN37WW",
        ):
            with self.subTest(bios=bios):
                plugins, _ = self.detect(bios=bios)
                self.assertEqual(plugins, [])

    def test_known_products_keep_precedence_without_reading_bios_or_vendor(self):
        for configs, plugin_type in (
            (LEGION_GO_CONFS, LegionGoControllersPlugin),
            (LEGION_S_CONFS, LegionGoSControllerPlugin),
        ):
            for product, config in configs.items():
                with self.subTest(product=product):
                    plugins, reader = self.detect(product=f" {product}\n")
                    self.assertEqual(len(plugins), 1)
                    self.assertIsInstance(plugins[0], plugin_type)
                    self.assertIs(plugins[0].dconf, config)
                    reader.assert_called_once_with(
                        "/sys/devices/virtual/dmi/id/product_name"
                    )

    def test_existing_plugins_returned_without_reading_dmi(self):
        existing = [LegionGoControllersPlugin(dconf=LEGION_GO_CONFS["83E1"])]
        with patch("builtins.open") as reader:
            self.assertIs(autodetect(existing), existing)
        reader.assert_not_called()

    def test_fallback_is_logged(self):
        with self.assertLogs("hhd.device.legion_go", level="INFO") as logs:
            plugins, _ = self.detect()
        self.assert_original_go(plugins)
        self.assertIn("original Legion Go via BIOS fallback", logs.output[0])
        self.assertIn("N3CN40WW", logs.output[0])


if __name__ == "__main__":
    unittest.main()
