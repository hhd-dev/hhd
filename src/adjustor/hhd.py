import logging
import os
from time import sleep
from typing import TYPE_CHECKING, Any, Sequence

from hhd.plugins import Context, HHDPlugin, HHDSettings, load_relative_yaml
from hhd.plugins.conf import Config

logger = logging.getLogger(__name__)


def write_sysfs(dir: str, fn: str, val: Any):
    with open(os.path.join(dir, fn), "w") as f:
        f.write(str(val))


def read_sysfs(dir: str, fn: str, default: str | None = None):
    try:
        with open(os.path.join(dir, fn), "r") as f:
            return f.read().strip()
    except Exception as e:
        if default is not None:
            return default
        raise e


class AdjustorPlugin(HHDPlugin):
    def __init__(self) -> None:
        self.name = f"adjustor"
        self.priority = 4
        self.log = "adjs"

        self.display = None
        self.max_brightness = 255

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

    return [AdjustorPlugin()]
