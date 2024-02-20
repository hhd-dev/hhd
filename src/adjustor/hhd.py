from adjustor.core.acpi import initialize, check_perms

from typing import Sequence

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

    def settings(self) -> HHDSettings:
        out = {"tdp": {"general": load_relative_yaml("settings.yml")}}
        if not self.enabled:
            del out["tdp"]["general"]["children"]["set_limits"]
        return out

    def open(
        self,
        emit,
        context: Context,
    ):
        self.emit = emit

    def update(self, conf: Config):
        new_enabled = conf["tdp.general.enable"].to(bool)
        if new_enabled != self.enabled:
            self.emit({"type": "settings"})
        self.enabled = new_enabled

    def close(self):
        pass


def autodetect(existing: Sequence[HHDPlugin]) -> Sequence[HHDPlugin]:
    if len(existing):
        return existing

    from .drivers.lenovo import LenovoDriverPlugin
    from .drivers.smu import SmuDriverPlugin, SmuQamPlugin
    from .core.const import DEV_PARAMS_LEGO, ALIB_PARAMS_REMBRANDT

    drivers = [
        AdjustorInitPlugin(),
        LenovoDriverPlugin(),
        SmuDriverPlugin(DEV_PARAMS_LEGO, ALIB_PARAMS_REMBRANDT),
        SmuQamPlugin(DEV_PARAMS_LEGO),
    ]

    if not drivers:
        logger.debug(f"No tdp drivers found for this device, exiting Adjustor.")
        return []

    return [*drivers, AdjustorPlugin()]
