from adjustor.core.acpi import initialize, check_perms

from typing import Sequence
from adjustor.core.const import CPU_DATA

import os
from hhd.plugins import (
    HHDPlugin,
    Context,
)
from hhd.plugins import HHDSettings, load_relative_yaml
import logging

from hhd.plugins.conf import Config

logger = logging.getLogger(__name__)


class AdjustorInitPlugin(HHDPlugin):
    def __init__(self) -> None:
        self.name = f"adjustor_init"
        self.priority = 5
        self.log = "adji"
        self.init = False
        self.failed = False

    def settings(self):
        return {}

    def update(self, conf: Config):
        if self.failed:
            conf["tdp.general.enable"] = False
        if self.init:
            return

        if not conf["tdp.general.enable"].to(bool):
            return

        initialize()
        if not check_perms():
            conf["tdp.general.enable"] = False
            conf["tdp.general.error"] = (
                "Can not write to 'acpi_call'. It is required for TDP."
            )
            self.failed = True

        self.init = True


class AdjustorPlugin(HHDPlugin):
    def __init__(self) -> None:
        self.name = f"adjustor_main"
        self.priority = 10
        self.log = "adjs"
        self.enabled = False
        self.enfoce_limits = True

    def settings(self) -> HHDSettings:
        return {"tdp": {"general": load_relative_yaml("settings.yml")}}

    def open(
        self,
        emit,
        context: Context,
    ):
        self.emit = emit

    def update(self, conf: Config):
        new_enabled = conf["tdp.general.enable"].to(bool)
        new_enforce_limits = conf["tdp.general.enforce_limits"].to(bool)
        if new_enabled != self.enabled or new_enforce_limits != self.enfoce_limits:
            self.emit({"type": "settings"})
        self.enabled = new_enabled
        self.enfoce_limits = new_enforce_limits

    def close(self):
        pass


def autodetect(existing: Sequence[HHDPlugin]) -> Sequence[HHDPlugin]:
    if len(existing):
        return existing

    from .drivers.lenovo import LenovoDriverPlugin
    from .drivers.smu import SmuDriverPlugin, SmuQamPlugin

    drivers = []
    with open("/sys/devices/virtual/dmi/id/product_name") as f:
        prod = f.read().strip()
    with open("/proc/cpuinfo") as f:
        cpuinfo = f.read().strip()

    drivers_matched = False
    legion_go = False
    if prod == "83E1":
        drivers.append(LenovoDriverPlugin())
        drivers_matched = True
        legion_go = True

    if (
        os.environ.get("HHD_ADJ_DEBUG")
        or os.environ.get("HHD_ENABLE_SMU")
        or not drivers_matched
    ):
        for name, (dev, cpu) in CPU_DATA.items():
            if name in cpuinfo:
                drivers.append(SmuDriverPlugin(dev, cpu))
                drivers.append(
                    SmuQamPlugin(
                        dev,
                        platform_profile=(
                            not legion_go or bool(os.environ.get("HHD_ADJ_DEBUG"))
                        ),
                    ),
                )
                break

    if not drivers:
        logger.info(f"No tdp drivers found for this device, exiting Adjustor.")
        return []

    return [
        *drivers,
        AdjustorInitPlugin(),
        AdjustorPlugin(),
    ]
