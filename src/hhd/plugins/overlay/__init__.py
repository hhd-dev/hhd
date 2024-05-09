import logging
from typing import TYPE_CHECKING, Any, Sequence

from hhd.plugins import Config, Context, Event, HHDPlugin, load_relative_yaml

logger = logging.getLogger(__name__)


class OverlayPlugin(HHDPlugin):
    def __init__(self) -> None:
        self.name = f"overlay"
        self.priority = 75
        self.log = "ovrl"
        self.ovf = None
        self.enabled = False
        self.has_executable = False

    def open(
        self,
        emit,
        context: Context,
    ):
        try:
            from .base import OverlayService
            from .overlay import find_overlay_exe
            from .x11 import QamHandler

            self.ovf = OverlayService(context, emit)
            self.has_executable = bool(find_overlay_exe(context))
            self.qam_handler = QamHandler(context)
            emit.register_qam(self.qam_handler)
            self.emit = emit
        except Exception as e:
            logger.warning(
                f"Could not init overlay service, is python-xlib installed? Error:\n{e}"
            )
            self.ovf = None

    def settings(self):
        if not self.ovf:
            return {}
        return {"hhd": {"settings": load_relative_yaml("settings.yml")}}

    def update(self, conf: Config):
        # Or with self.enabled to require restart
        self.enabled = self.enabled or conf.get("hhd.settings.overlay_enabled", False)
        self.emit.set_simple_qam(not self.enabled or not self.has_executable)

    def notify(self, events: Sequence[Event]):
        if not self.ovf:
            return

        for ev in events:
            if ev["type"] != "special":
                continue

            override_enable = False
            match ev["event"]:
                # We can listen to steam and mute it
                # So we can ignore QAM and Guide presses
                # case "guide":
                #     # Close to avoid issues with steam
                #     cmd = "close_now"
                # case "qam_single":
                #     # Close to avoid issues with steam
                #     cmd = "close"
                # case "guide_b":
                #     # Open QAM with guide_b
                #     cmd = "open_qam"
                case "qam_hold":
                    # Open QAM with hold for accessibility
                    cmd = "open_qam"
                case "qam_predouble":
                    cmd = "open_qam_if_closed"
                case "qam_double":
                    # Preferred bind for QAM is dual press
                    cmd = "open_qam"
                case "overlay":
                    override_enable = True
                    cmd = "open_qam"
                case "qam_tripple":
                    # Allow opening expanded menu with tripple press
                    cmd = "open_expanded"
                case _:
                    cmd = None

            if cmd and (self.enabled or override_enable):
                init = "close" not in cmd
                if init:
                    logger.info(f"Executing overlay command: '{cmd}'")
                self.ovf.update(cmd, init)

    def close(self):
        if self.ovf:
            self.ovf.close()
        if self.qam_handler:
            self.qam_handler.close()


def autodetect(existing: Sequence[HHDPlugin]) -> Sequence[HHDPlugin]:
    if len(existing):
        return existing

    return [OverlayPlugin()]
