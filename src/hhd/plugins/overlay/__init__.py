import logging
from typing import TYPE_CHECKING, Any, Sequence

from hhd.plugins import Config, Context, HHDPlugin, load_relative_yaml

logger = logging.getLogger(__name__)


class OverlayPlugin(HHDPlugin):
    def __init__(self) -> None:
        self.name = f"overlay"
        self.priority = 95
        self.log = "ovrl"

    def open(
        self,
        emit,
        context: Context,
    ):
        self.started = False
        self.context = context

    def settings(self):
        d = {"hhd": {"overlay": load_relative_yaml("settings.yml")}}
        # if self.cfg.unsupported:
        #     d["hhd"]["overlay"]["children"]["powerbuttond"]["default"] = False
        return d

    def update(self, conf: Config):
        pass

    def start(self):
        pass

    def stop(self):
        pass

    def close(self):
        self.stop()


def autodetect(existing: Sequence[HHDPlugin]) -> Sequence[HHDPlugin]:
    if len(existing):
        return existing

    return []
