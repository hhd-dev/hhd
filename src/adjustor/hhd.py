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

    def settings(self) -> HHDSettings:
        return {"tdp": {"adjustor": load_relative_yaml("settings.yml")}}

    def open(
        self,
        emit,
        context: Context,
    ):
        pass

    def update(self, conf: Config):
        pass

    def close(self):
        pass


def autodetect(existing: Sequence[HHDPlugin]) -> Sequence[HHDPlugin]:
    if len(existing):
        return existing
    
    from .drivers.lenovo import LenovoDriverPlugin
    drivers = [
        LenovoDriverPlugin()
    ]

    if not drivers:
        logger.debug(f"No tdp drivers found for this device, exiting Adjustor.")
        return []

    return [*drivers, AdjustorPlugin()]
