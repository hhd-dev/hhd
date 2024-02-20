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


class LenovoDriverPlugin(HHDPlugin):
    def __init__(self) -> None:
        self.name = f"adjustor_lenovo"
        self.priority = 6
        self.log = "adjl"
        self.enabled = False

    def settings(self):
        if not self.enabled:
            return {}
        return {"tdp": {"lenovo": load_relative_yaml("settings.yml")}}

    def open(
        self,
        emit,
        context: Context,
    ):
        pass

    def update(self, conf: Config):
        self.enabled = conf['tdp.general.enable'].to(bool)

    def close(self):
        pass
