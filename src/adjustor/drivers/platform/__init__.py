from hhd.plugins import (
    HHDPlugin,
    Context,
)
from hhd.plugins import load_relative_yaml
import logging

from hhd.plugins.conf import Config

logger = logging.getLogger(__name__)


class PlatformProfilePlugin(HHDPlugin):
    def __init__(self) -> None:
        self.name = f"adjustor_platform_profile"
        self.priority = 5
        self.log = "appf"

    def settings(self):
        return {
            "tdp": {
                "adjustor": {
                    "type": "container",
                    "children": {
                        "platform_profile": load_relative_yaml("settings.yml"),
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
