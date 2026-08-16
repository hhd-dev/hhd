import logging
import os
from threading import Event, Thread
from typing import Sequence

from hhd.plugins import Config, Context, Emitter, HHDPlugin, load_relative_yaml

logger = logging.getLogger(__name__)

SUPPORTS_CEC = os.environ.get("HHD_GS_CEC", "0") == "1"


class CecPlugin(HHDPlugin):
    def __init__(self) -> None:
        self.name = "cec"
        self.priority = 74
        self.log = "CEC"
        self.thread: Thread | None = None
        self.should_exit: Event | None = None
        self.emit: Emitter | None = None

    def open(self, emit: Emitter, context: Context):
        self.emit = emit

    def settings(self):
        return {
            "hhd": load_relative_yaml("settings.yml"),
            "shortcuts": load_relative_yaml("shortcuts.yml"),
        }

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        from .service import cec_run

        logger.info("Starting HDMI-CEC service.")
        self.should_exit = Event()
        self.thread = Thread(
            target=cec_run,
            args=(self.should_exit, self.emit),
            name="hhd-cec",
        )
        self.thread.start()

    def stop(self):
        if self.should_exit:
            self.should_exit.set()
        if self.thread:
            self.thread.join()
        if self.should_exit or self.thread:
            logger.info("Stopped HDMI-CEC service.")
        self.should_exit = None
        self.thread = None

    def update(self, conf: Config):
        requested = conf.get("hhd.settings.cec", True)
        if requested and (not self.thread or not self.thread.is_alive()):
            self.stop()
            self.start()
        elif not requested and self.thread:
            self.stop()

    def close(self):
        self.stop()


def autodetect(existing: Sequence[HHDPlugin]) -> Sequence[HHDPlugin]:
    if not SUPPORTS_CEC:
        return []
    if existing:
        return existing
    return [CecPlugin()]
