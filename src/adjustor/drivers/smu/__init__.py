from typing import Any, Sequence, TYPE_CHECKING
import os
from hhd.plugins import (
    HHDPlugin,
    Context,
)
from hhd.plugins import load_relative_yaml
import logging

from hhd.plugins.conf import Config

logger = logging.getLogger(__name__)


class SmuQamPlugin(HHDPlugin):
    def __init__(self) -> None:
        self.name = f"adjustor_smu_qam"
        self.priority = 6
        self.log = "smuq"

    def settings(self):
        return {"tdp": {"qam": load_relative_yaml("qam.yml")}}

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


class SmuDriverPlugin(HHDPlugin):
    def __init__(self) -> None:
        self.name = f"adjustor_smu"
        self.priority = 9
        self.log = "asmu"

    def settings(self):
        return {
            "tdp": {
                "smu": load_relative_yaml("smu.yml"),
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
