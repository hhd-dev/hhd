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
        self.initialized = False

    def settings(self):
        if not self.enabled:
            self.initialized = False
            return {}
        self.initialized = True
        return {"tdp": {"lenovo": load_relative_yaml("settings.yml")}}

    def open(
        self,
        emit,
        context: Context,
    ):
        pass

    def update(self, conf: Config):
        self.enabled = conf['tdp.general.enable'].to(bool)
        if not self.enabled or not self.initialized:
            return
        
        

        self.old_conf = conf['tdp.lenovo']

        

    def close(self):
        pass
