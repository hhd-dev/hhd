from typing import Any, Sequence, TYPE_CHECKING

from hhd.plugins import (
    HHDPlugin,
    Context,
)

if TYPE_CHECKING:
    from .const import PowerButtonConfig
from threading import Event, Thread


def run(**config: Any):
    from .base import power_button_run

    power_button_run(**config)


class PowerbuttondPlugin(HHDPlugin):
    def __init__(self, cfg: PowerButtonConfig) -> None:
        self.name = f"powerbuttond@{cfg.device}"
        self.priority = 20
        self.cfg = cfg

    def open(
        self,
        emit,
        context: Context,
    ):
        from .base import power_button_run

        self.event = Event()
        self.t = Thread(target=power_button_run, args=(self.cfg, context, self.event))
        self.t.start()

    def close(self):
        self.event.set()
        self.t.join()


def autodetect(existing: Sequence[HHDPlugin]) -> Sequence[HHDPlugin]:
    if len(existing):
        return []

    from .base import get_config

    cfg = get_config()
    if not cfg:
        return []

    return [PowerbuttondPlugin(cfg)]
