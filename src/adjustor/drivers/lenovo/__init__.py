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


BRICK_HINT = """
Disables Lenovo TDP handling when using other drivers.

This "hack" sets a leftover TDP mode lenovo calls Extreme Mode.
This mode is partially implemented by Lenovo, causing the Embedded Computer
to bug and disable all TDP handling.
It is required to use methods such as ALIB or RyzenAdj without the Embedded
Computer interfering, as it is programmed to periodically set TDP values.
This setting will be autoreset when Handheld Daemon shuts down by setting
the TDP mode to Balanced.

When this setting is active, `Legion L + Y` will no longer work.
In addition, Extreme Mode programs the Ryzen Processor to use 0W TDP
(as the parameter is initialized to 0 and never set before being sent to the 
processor), so if you reboot, the Go may have trouble booting.

In any case, this change can be reverted either by going to the BIOS and setting
the TDP Mode there, or by holding the Power Button for around 20s when the GO
is closed to trigger an Embedded Computer reset (the controller lights will
flash red twice).
"""


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
                        },  # type: ignore
                        "fan": load_relative_yaml("fans.yml"),
                        "brick_lenovo": {
                            "type": "bool",
                            "title": "For other drivers, disable Lenovo TDP (hack).",
                            "hint": BRICK_HINT,
                            "default": False,
                        },
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
