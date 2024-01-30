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

    def settings(self) -> HHDSettings:
        return {
            "tdp": {
                "adjustor": {
                    "type": "container",
                    "children": {
                        "tdp_mode": {
                            "type": "mode",
                            "modes": {"lenovo": load_relative_yaml("tdp.yml")},
                        },
                        "fan": load_relative_yaml("fans.yml"),
                    },
                }
            }
        }

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
