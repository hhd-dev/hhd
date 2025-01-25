import logging
import os
from threading import Event as TEvent
from threading import Thread
from typing import Sequence

from hhd.plugins import Config, Context, Event, HHDPlugin, load_relative_yaml
from hhd.utils import expanduser

from ..plugin import open_steam_kbd
from .const import get_system_info, get_touchscreen_quirk
from .controllers import QamHandlerKeyboard, device_shortcut_loop
from .steam import get_games
from .x11 import is_gamescope_running

logger = logging.getLogger(__name__)

SHORTCUT_RELOAD_DELAY = 2

HHD_OVERLAY_DISABLE = os.environ.get("HHD_OVERLAY_DISABLE", "0") == "1"
FORCE_GAME = os.environ.get("HHD_FORCE_GAME_ID", None)
SUPPORTS_HALVING = os.environ.get("HHD_GS_STEAMUI_HALFHZ", "0") == "1"
SUPPORTS_DPMS = os.environ.get("HHD_GS_DPMS", "0") == "1"


def load_steam_games(ctx: Context, emit, burnt_ids: set):
    # Defer loading until we enter a game
    info = emit.info
    curr = info.get("game.id", None)
    # Lump steam into none to avoid loading twice
    if info.get("game.is_steam", False):
        curr = None

    # If the game changes and we do not have data for it do a reload
    if curr in burnt_ids:
        return None, None

    if "games" in info and curr in info.get("games", {}):
        return None, None

    # Maybe a game is missing from appcache, if it is burn it
    # so we dont try to load the library again
    burnt_ids.add(curr)

    try:
        # Load the games
        games, images = get_games(expanduser("~/.local/share/Steam/appcache/", ctx))
        logger.info(f"Loaded info for {len(games)} steam games.")

        # Add correct game data after refreshing the database (e.g., the user
        # downloaded a new game)
        if curr and curr in games:
            emit.info["game.data"] = games[curr]

        return games, images
    except Exception as e:
        logger.warning(f"Could not load steam games:\n{e}")
        return None, None


class OverlayPlugin(HHDPlugin):
    def __init__(self) -> None:
        self.name = f"overlay"
        self.priority = 75
        self.log = "ovrl"
        self.ovf = None
        self.initialized = False
        self.old_shortcuts = None
        self.short_should_exit = None
        self.has_correction = True
        self.old_touch = False
        self.old_asus_cycle = None
        self.short_t = None
        self.has_executable = False
        self.qam_handler = None
        self.qam_handler_fallback = None
        self.touch_gestures = True
        self.ctx = None

        self.images = None
        self.burnt_ids = set()

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
            self.ctx = context
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
            else:
                self.qam_handler_fallback = QamHandlerKeyboard()
            self.emit = emit
        except Exception as e:
            logger.warning(
                f"Could not init overlay service, is python-xlib installed? Error:\n{e}"
            )
            self.ovf = None

    def settings(self):
        if not self.ovf:
            return {}

        self.initialized = True
        set = {
            "gamemode": load_relative_yaml("gamemode.yml"),
            "shortcuts": load_relative_yaml("shortcuts.yml"),
        }

        if not SUPPORTS_HALVING:
            del set["gamemode"]["gamescope"]["children"]["steamui_halfhz"]
        if not SUPPORTS_DPMS:
            del set["gamemode"]["gamescope"]["children"]["dpms"]

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
        self.emit.set_simple_qam(not self.has_executable)

        # Load game information
        if self.ctx:
            games, images = load_steam_games(self.ctx, self.emit, self.burnt_ids)
            if games and images:
                self.emit.set_gamedata(games, images)
        if FORCE_GAME:
            self.emit.info["game.id"] = FORCE_GAME
            self.emit.info["game.is_steam"] = False
            self.emit.info["game.data"] = self.emit.get_gamedata(FORCE_GAME)
        if self.ovf:
            self.ovf.launch_overlay()

        self.touch_gestures = not bool(
            conf.get("gamemode.display.gestures_disable", False)
        )
        if SUPPORTS_HALVING and self.ovf:
            self.ovf.gsconf["steamui_halfhz"] = conf.get(
                "gamemode.gamescope.steamui_halfhz", False
            )
        if SUPPORTS_DPMS and self.ovf:
            self.ovf.gsconf["dpms"] = conf.get("gamemode.gamescope.dpms", False)

        disable_touch = conf.get("gamemode.display.touchscreen_disable", False)
        if disable_touch is None:
            # Initialize value since there is no default
            disable_touch = False
            conf["gamemode.display.touchscreen_disable"] = False

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
        if self.ovf:
            self.ovf.notify(events)

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
                case "xbox_y":
                    side = "xbox_y"
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
                case "qam_triple":
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
                        d = ev.get("data", None)
                        uniq = d.get("uniq", None) if d else None
                        import re

                        # Make sure uniq is kind of a mac address
                        # We are a root level daemon
                        if uniq and re.match(r"([\d:]+)", uniq):
                            logger.warning(
                                f"Disconnecting controller with uniq: {uniq}"
                            )
                            os.system("bluetoothctl disconnect " + uniq)
                    case "hhd_qam":
                        cmd = "open_qam"
                    case "hhd_expanded":
                        cmd = "open_expanded"
                    case "steam_qam":
                        logger.info("Opening steam qam.")
                        if (
                            not self.emit.open_steam(False)
                            and self.qam_handler_fallback
                        ):
                            self.qam_handler_fallback(False)
                    case "steam_expanded":
                        logger.info("Opening steam expanded.")
                        if not self.emit.open_steam(True) and self.qam_handler_fallback:
                            self.qam_handler_fallback(True)
                    case "keyboard":
                        if open_steam_kbd(self.emit, True):
                            logger.info("Opened Steam keyboard.")
                        else:
                            logger.warning(
                                "Could not open Steam keyboard. Is Steam running?"
                            )
                    case "screenshot":
                        logger.info("Taking screenshot.")
                        if self.qam_handler and hasattr(self.qam_handler, "screenshot"):
                            getattr(self.qam_handler, "screenshot")()
                        elif self.qam_handler_fallback:
                            self.qam_handler_fallback.screenshot()

            if self.ovf and cmd:
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
        if self.qam_handler_fallback:
            self.qam_handler_fallback.close()
        self._close_short()


def autodetect(existing: Sequence[HHDPlugin]) -> Sequence[HHDPlugin]:
    if HHD_OVERLAY_DISABLE:
        return []

    if len(existing):
        return existing

    return [OverlayPlugin()]
