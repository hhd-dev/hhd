from typing import Any, Sequence, TYPE_CHECKING
import os
from hhd.plugins import (
    HHDPlugin,
    Context,
)
from hhd.plugins import HHDSettings, load_relative_yaml
import logging

from hhd.plugins.conf import Config

logger = logging.getLogger(__name__)


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
        LenovoDriverPlugin(),
        SmuDriverPlugin(DEV_PARAMS_LEGO, ALIB_PARAMS_REMBRANDT),
        SmuQamPlugin(DEV_PARAMS_LEGO),
    ]

    if not drivers:
        logger.debug(f"No tdp drivers found for this device, exiting Adjustor.")
        return []

    return [*drivers, AdjustorPlugin()]
