import logging
from typing import TYPE_CHECKING, Any, Sequence

from hhd.plugins import Config, Context, HHDPlugin, load_relative_yaml

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .const import PowerButtonConfig

from threading import Event, Thread


def run(**config: Any):
    from .base import power_button_run

    power_button_run(**config)


class PowerbuttondPlugin(HHDPlugin):
    def __init__(self, cfg: "PowerButtonConfig") -> None:
        self.name = f"powerbuttond@'{cfg.device}'"
        self.priority = 90
        self.log = "pbtn"
        self.cfg = cfg
        self.t = None
        self.event = None
        self.emit = None

    def open(
        self,
        emit,
        context: Context,
    ):
        self.started = False
        self.context = context
        self.emit = emit

    def settings(self):
        d = {"hhd": load_relative_yaml("settings.yml")}
        # if self.cfg.unsupported:
        #     d["hhd"]["settings"]["children"]["powerbuttond"]["default"] = False
        return d

    def update(self, conf: Config):
        if conf["hhd.settings.powerbuttond"].to(bool) and not self.started:
            self.start()
        elif not conf["hhd.settings.powerbuttond"].to(bool) and self.started:
            self.stop()
            logger.info('Stopping Steam Powerbutton Handler.')

    def start(self):
        from .base import power_button_run

        self.event = Event()
        self.t = Thread(
            target=power_button_run, args=(self.cfg, self.context, self.event, self.emit)
        )
        self.t.start()
        self.started = True

    def stop(self):
        if not self.event or not self.t:
            return
        self.event.set()
        self.t.join()
        self.event = None
        self.t = None
        self.started = False

    def close(self):
        self.stop()


def autodetect(existing: Sequence[HHDPlugin]) -> Sequence[HHDPlugin]:
    if len(existing):
        return existing

    from .const import get_config

    return [PowerbuttondPlugin(get_config())]
