import logging
import os
from threading import Event as TEvent
from threading import Thread
from typing import Sequence

from hhd.plugins import Config, Context, Event, HHDPlugin, load_relative_yaml

from ..plugin import open_steam_kbd
from .const import get_system_info, get_touchscreen_quirk
from .controllers import QamHandlerKeyboard, device_shortcut_loop
from .x11 import is_gamescope_running

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
        self.has_correction = True
        self.old_touch = False
        self.old_asus_cycle = None
        self.short_t = None
        self.has_executable = False

    def open(
        self,
        emit,
        context: Context,
    ):
        try:
            from .base import OverlayService
            from .overlay import find_overlay_exe
            from .x11 import QamHandlerGamescope

            self.ovf = OverlayService(context, emit)
            self.has_executable = bool(find_overlay_exe(context))

            if bool(os.environ.get("HHD_QAM_KEYBOARD", None)):
                # Sends the events as ctrl+1, ctrl+2
                self.qam_handler = QamHandlerKeyboard()
            elif bool(os.environ.get("HHD_QAM_GAMESCOPE", None)):
                # Sends X11 events to gamescope. Stopped working after libei
                self.qam_handler = QamHandlerGamescope(context)
            else:
                self.qam_handler = None

            if self.qam_handler:
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

            if get_touchscreen_quirk(None, None)[0] and not os.environ.get(
                "HHD_ALLOW_CORRECTION", None
            ):
                # For devices with a dmi match, hide orientation correction
                self.has_correction = False
                del set["shortcuts"]["touchscreen"]["children"]["orientation"]
            else:
                self.has_correction = True
                set["shortcuts"]["touchscreen"]["children"]["orientation"]["modes"][
                    "manual"
                ]["children"]["dmi"]["default"] = " - ".join(
                    map(lambda x: f'"{x}"', get_system_info())
                )
        return set

    def update(self, conf: Config):
        # Or with self.enabled to require restart
        new_enabled = conf.get("hhd.settings.overlay_enabled", False)
        if new_enabled != self.enabled:
            self.emit({"type": "settings"})
        self.enabled = self.enabled or new_enabled
        self.emit.set_simple_qam(not self.enabled or not self.has_executable)

        self.touch_gestures = not bool(
            conf.get("controllers.touchscreen.gestures_disable", False)
        )
        disable_touch = conf.get("controllers.touchscreen.disable", False)
        if disable_touch is None:
            # Initialize value since there is no default
            disable_touch = False
            conf["controllers.touchscreen.disable"] = False

        asus_cycle = conf.get("tdp.asus.cycle_tdp", False)
        if self.initialized and (
            not self.old_shortcuts
            or self.old_shortcuts != conf["shortcuts"]
            or self.old_touch != disable_touch
            or self.old_asus_cycle != asus_cycle
        ):
            self.old_asus_cycle = asus_cycle
            self.old_shortcuts = conf["shortcuts"].copy()
            self._close_short()

            kbd = False
            for v in ("meta_press", "meta_hold", "ctrl_3", "ctrl_4"):
                kbd = (
                    kbd or conf.get(f"shortcuts.keyboard.{v}", "disabled") != "disabled"
                )
            touch = False
            for v in ("bottom", "left_top", "left_bottom", "right_top", "right_bottom"):
                touch = (
                    touch
                    or conf.get(f"shortcuts.touchscreen.{v}", "disabled") != "disabled"
                )
            # ctrl = (
            #     conf.get("shortcuts.controller.xbox_b", "disabled") != "disabled"
            #     or asus_cycle
            # )
            # For now always monitor controllers to be able to grab
            ctrl = True
            # if self.ovf:
            #     self.ovf.interceptionSupported = True

            if kbd or touch or ctrl or disable_touch:
                logger.info(
                    f"Starting shortcut loop with:\nkbd: {kbd}, touch: {touch}, ctrl: {ctrl}, disable_touch: {disable_touch}"
                )
                self.short_should_exit = TEvent()
                touch_correction = (
                    conf.get("shortcuts.touchscreen.orientation.manual", None)
                    if self.has_correction
                    and conf.get("shortcuts.touchscreen.orientation.mode", "auto")
                    == "manual"
                    else None
                )
                self.short_t = Thread(
                    target=device_shortcut_loop,
                    args=(
                        self.emit,
                        self.short_should_exit,
                        False,
                        kbd,
                        ctrl,
                        touch,
                        disable_touch,
                        touch_correction,
                    ),
                )
                self.short_t.start()
                self.old_touch = disable_touch
            else:
                logger.info("No shortcuts enabled, not starting shortcut loop.")

    def notify(self, events: Sequence[Event]):
        for ev in events:
            if ev["type"] != "special":
                continue

            side = None
            section = None
            override_enable = False
            match ev["event"]:
                case gesture if gesture.startswith("swipe_"):
                    if self.touch_gestures:
                        side = gesture[len("swipe_") :]
                        section = "touchscreen"
                    cmd = None
                case gesture if gesture.startswith("kbd_"):
                    if is_gamescope_running():
                        # Only allow kbd shortcuts while gamescope is open
                        # Cannot be used in big picture because KDE/GNOME
                        side = gesture[len("kbd_") :]
                        section = "keyboard"
                    cmd = None
                case "xbox_b":
                    side = "xbox_b"
                    section = "controller"
                case 'xbox_y':
                    side = 'xbox_y'
                    section = 'controller'
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
                logger.info(f"Gesture: {ev['event']}, section: {section}, key: {side}")
                cmd_raw = self.old_shortcuts.get(f"{section}.{side}", "disabled")
                cmd = None
                match cmd_raw:
                    case "disconnect":
                        d = ev.get('data', None)
                        uniq = d.get('uniq', None) if d else None
                        import re
                        # Make sure uniq is kind of a mac address
                        # We are a root level daemon
                        if uniq and re.match(r'([\d:]+)', uniq):
                            logger.warning(f"Disconnecting controller with uniq: {uniq}")
                            os.system("bluetoothctl disconnect " + uniq)
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
                        if open_steam_kbd(self.emit, True):
                            logger.info("Opened Steam keyboard.")
                        else:
                            logger.warning(
                                "Could not open Steam keyboard. Is Steam running?"
                            )

            if self.ovf and cmd and (self.enabled or override_enable):
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
