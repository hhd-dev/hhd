import logging
from threading import Event as TEvent
from threading import Thread
import time
from typing import Sequence

from hhd.plugins import Config, Context, Event, HHDPlugin, load_relative_yaml

from ..plugin import open_steam_kbd, is_steam_gamepad_running
from .controllers import device_shortcut_loop

logger = logging.getLogger(__name__)

SHORTCUT_RELOAD_DELAY = 2


class OverlayPlugin(HHDPlugin):
    def __init__(self) -> None:
        self.name = f"overlay"
        self.priority = 75
        self.log = "ovrl"
        self.ovf = None
        self.enabled = False
        self.initialized = False
        self.old_shortcuts = None
        self.short_should_exit = None
        self.old_touch = False
        self.short_t = None
        self.init = True
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
        set = {"hhd": {"settings": load_relative_yaml("settings.yml")}}
        if self.enabled:
            self.initialized = True
            set["shortcuts"] = load_relative_yaml("shortcuts.yml")
            set["controllers"] = load_relative_yaml("touchcontrols.yml")
        return set

    def update(self, conf: Config):
        # Or with self.enabled to require restart
        new_enabled = conf.get("hhd.settings.overlay_enabled", False)
        if new_enabled != self.enabled:
            self.emit({"type": "settings"})
        self.enabled = self.enabled or new_enabled
        self.emit.set_simple_qam(not self.enabled or not self.has_executable)

        disable_touch = conf.get("controllers.touchscreen.disable", False)
        if self.initialized and (
            not self.old_shortcuts
            or self.old_shortcuts != conf["shortcuts"]
            or self.old_touch != disable_touch
        ):
            self.old_shortcuts = conf["shortcuts"].copy()
            self._close_short()

            kbd = False
            for v in ("meta_press", "meta_hold"):
                kbd = (
                    kbd or conf.get(f"shortcuts.keyboard.{v}", "disabled") != "disabled"
                )
            touch = False
            for v in ("bottom", "left_top", "left_bottom", "right_top", "right_bottom"):
                touch = (
                    touch
                    or conf.get(f"shortcuts.touchscreen.{v}", "disabled") != "disabled"
                )
            ctrl = conf.get("shortcuts.controller.xbox_b", "disabled") != "disabled"

            if kbd or touch or ctrl or disable_touch:
                logger.info(
                    f"Starting shortcut loop with kbd: {kbd}, touch: {touch}, ctrl: {ctrl}, disable_touch: {disable_touch}."
                )
                self.short_should_exit = TEvent()
                self.short_t = Thread(
                    target=device_shortcut_loop,
                    args=(
                        self.emit,
                        self.short_should_exit,
                        self.init,
                        kbd,
                        ctrl,
                        touch,
                        disable_touch,
                    ),
                )
                self.short_t.start()
                self.init = False
                self.old_touch = disable_touch
            else:
                logger.info("No shortcuts enabled, not starting shortcut loop.")

    def notify(self, events: Sequence[Event]):
        if not self.ovf:
            return

        for ev in events:
            if ev["type"] != "special":
                continue

            side = None
            section = None
            override_enable = False
            match ev["event"]:
                case gesture if gesture.startswith("swipe_"):
                    side = gesture[len("swipe_") :]
                    section = "touchscreen"
                    cmd = None
                case gesture if gesture.startswith("kbd_"):
                    if is_steam_gamepad_running(self.emit.ctx, True):
                        # Only allow kbd shortcuts while steam is in big
                        # picture mode
                        side = gesture[len("kbd_") :]
                        section = "keyboard"
                    cmd = None
                case "qam_external":
                    side = "xbox_b"
                    section = "controller"
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

            if section and side and self.old_shortcuts:
                cmd_raw = self.old_shortcuts.get(f"{section}.{side}", "disabled")
                cmd = None
                match cmd_raw:
                    case "hhd_qam":
                        cmd = "open_qam"
                    case "hhd_expanded":
                        cmd = "open_expanded"
                    case "steam_qam":
                        logger.info("Opening steam qam.")
                        self.emit.open_steam(False)
                    case "steam_expanded":
                        logger.info("Opening steam expanded.")
                        self.emit.open_steam(True)
                    case "keyboard":
                        logger.info("Opening keyboard.")
                        open_steam_kbd(self.emit, True)

            if cmd and (self.enabled or override_enable):
                init = "close" not in cmd
                if init:
                    logger.info(f"Executing overlay command: '{cmd}'")
                self.ovf.update(cmd, init)

    def _close_short(self):
        if self.short_should_exit:
            self.short_should_exit.set()
            self.short_should_exit = None
        if self.short_t:
            self.short_t.join()
            self.short_t = None

    def close(self):
        if self.ovf:
            self.ovf.close()
        if self.qam_handler:
            self.qam_handler.close()
        self._close_short()


def autodetect(existing: Sequence[HHDPlugin]) -> Sequence[HHDPlugin]:
    if len(existing):
        return existing

    return [OverlayPlugin()]
