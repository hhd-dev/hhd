import logging
import os
import select
import subprocess
import time
from threading import Event as TEvent
from threading import Thread
from typing import Literal, cast

from Xlib import display

from hhd.plugins import Config, Context, Emitter

from .controllers import OverlayWriter
from .overlay import find_overlay_exe, inject_overlay, launch_overlay_de
from .systemd import WakeHandler
from .x11 import (
    HHD_ID,
    STEAM_ID,
    apply_gamescope_config,
    does_steam_exist,
    find_focusable_windows,
    find_hhd,
    find_steam,
    find_x11_auth,
    find_x11_display,
    get_current_game,
    get_gamescope_displays,
    get_overlay_display,
    hide_hhd,
    make_hhd_not_focusable,
    prepare_hhd,
    process_events,
    register_changes,
    set_dpms,
    show_hhd,
    update_steam_values,
)

logger = logging.getLogger(__name__)
Command = Literal[
    "close_now",
    "close",
    "open_qam",
    "open_qam_if_closed",
    "open_expanded",
    "open_notification",
]
Status = Literal["closed", "qam", "expanded", "notification"]

GUARD_CHECK = 0.5
STARTUP_MAX_DELAY = 10
LOOP_SLEEP = 0.05
OVERLAY_CHECK_INTERVAL = 5
GAME_CHECK_INTERVAL = 2

SUPPORTS_STANDBY = os.environ.get("HHD_GS_STANDBY", "0") == "1"

def standby_transition(state: str):
    if not SUPPORTS_STANDBY:
        return
    
    try:
        if not os.path.exists("/sys/power/standby"):
            return

        with open("/sys/power/standby", "w") as f:
            logger.info(f"Setting standby state to '{state}'.")
            f.write(state)
    except Exception as e:
        logger.error(f"Failed to set standby state to {state}:\n{e}")

def loop_manage_desktop(
    proc: subprocess.Popen,
    emit: Emitter,
    writer: OverlayWriter,
    should_exit: TEvent,
):
    try:
        assert proc.stderr and proc.stdout

        fd_out = proc.stdout.fileno()
        fd_err = proc.stderr.fileno()
        os.set_blocking(fd_out, False)
        os.set_blocking(fd_err, False)

        while not should_exit.is_set():
            start = time.perf_counter()
            select.select([fd_out, fd_err], [], [], GUARD_CHECK)

            if proc.poll() is not None:
                logger.warning(f"Overlay stopped (steam may have restarted). Closing.")
                return

            # Process system logs
            while True:
                l = proc.stderr.readline()[:-1]
                if not l:
                    break
                if l.strip():
                    logger.info(f"UI: {l}")

            # Update overlay status
            while True:
                cmd = proc.stdout.readline()[:-1]
                if not cmd:
                    break
                elif cmd.startswith("grab:"):
                    enable = cmd[5:] == "enable"
                    emit.grab(enable)
                    if not enable:
                        writer.reset()

            elapsed = time.perf_counter() - start
            if elapsed < LOOP_SLEEP:
                time.sleep(LOOP_SLEEP - elapsed)
    except Exception as e:
        logger.warning(f"The overlay process ended with an exception:\n{e}")
    finally:
        logger.info(f"Stopping overlay process.")
        proc.kill()
        proc.wait()
        emit.grab(False)


def loop_manage_overlay(
    disp: display.Display,
    proc: subprocess.Popen,
    emit: Emitter,
    writer: OverlayWriter,
    should_exit: TEvent,
    requested: bool,
    gsconf: Config,
):
    wake_handler = None
    try:
        status: Status = "closed"

        assert proc.stderr and proc.stdout

        fd_out = proc.stdout.fileno()
        fd_err = proc.stderr.fileno()
        os.set_blocking(fd_out, False)
        os.set_blocking(fd_err, False)
        fd_disp = disp.fileno()
        gsprev = {}

        # Give electron time to warmup
        start = time.perf_counter()
        curr = start
        while (
            curr - start < STARTUP_MAX_DELAY
            and (not find_hhd(disp) or not find_focusable_windows(disp))
            and not should_exit.is_set()
        ):
            time.sleep(GUARD_CHECK)
            curr = time.perf_counter()

        hhd = find_hhd(disp)
        steam = find_steam(disp)
        steam_exists = does_steam_exist(disp)
        old_game = None
        last_game_check = 0
        old = None
        shown = False
        wake_handler = None
        dpms_time = None

        if hhd:
            logger.info(f"UI window found in gamescope, starting handler.")
            prepare_hhd(disp, hhd, steam)
        if steam:
            register_changes(disp, steam)

        while not should_exit.is_set():
            if not hhd:
                logger.error(f"UI Window not found, exitting overlay.")
                break
            if not steam and steam_exists:
                logger.error(
                    f"Steam window not found but steam is active, exitting overlay."
                )
                break

            start = time.perf_counter()
            fds = [fd_out, fd_err, fd_disp]
            if wake_handler and wake_handler.fd != -1:
                fds.append(wake_handler.fd)
            select.select(fds, [], [], GUARD_CHECK)

            if proc.poll() is not None:
                logger.warning(f"Overlay stopped (steam may have restarted). Closing.")
                return

            # If steam tries to appear while the overlay is active
            # yank its focus
            process_events(disp)
            apply_gamescope_config(disp, gsconf, gsprev)

            # Handle dpms
            dpms_en = gsconf.get("dpms", False)
            if dpms_en and not wake_handler:
                wake_handler = WakeHandler()
                ret = wake_handler.start()
                if ret:
                    logger.info("Started DPMS handler.")
                else:
                    logger.error("Failed to start wake handler, DPMS will not work.")
            elif not dpms_en and wake_handler:
                wake_handler.close()
                wake_handler = None
                logger.info("Stopped DPMS handler.")
                if dpms_time:
                    set_dpms(disp, False)
            if dpms_en and wake_handler:
                s = wake_handler()
                if s == "entry":
                    set_dpms(disp, True)
                    standby_transition("sleep")
                    dpms_time = start
                    logger.info("Enabling gamescope DPMS.")
                    wake_handler.inhibit(False)
                elif s == "exit":
                    set_dpms(disp, False)
                    standby_transition("active")
                    dpms_time = None
                    logger.info("Disabling gamescope DPMS.")
                    wake_handler.inhibit(True)
            if dpms_time and start - dpms_time > 5:
                set_dpms(disp, False)
                dpms_time = None
                logger.error("DPMS timeout lapsed, disabling.")

            if steam and shown:
                old, was_shown = update_steam_values(disp, steam, old)
                if was_shown:
                    show_hhd(disp, hhd, steam)
                    logger.warning("Steam opened, hiding it.")

            if start - last_game_check > GAME_CHECK_INTERVAL:
                game = get_current_game(disp)
                if old_game != game:
                    emit.info["game.id"] = str(game)
                    is_steam = game in (STEAM_ID, HHD_ID, 7)
                    emit.info["game.is_steam"] = is_steam
                    game_data = emit.get_gamedata(str(game))
                    name = game_data["name"] if game_data else "Unknown Title"
                    emit.info["game.data"] = game_data
                    if is_steam:
                        logger.info(f"Switched to steam.")
                    else:
                        logger.info(f"Switched to game {game}: '{name}'.")
                    old_game = game

            # If we are running on a headless session
            # make sure hhd cant be focused
            if not steam and not shown:
                make_hhd_not_focusable(disp)

            # Process system logs
            while True:
                l = proc.stderr.readline()[:-1]
                if not l:
                    break
                if l.strip():
                    logger.info(f"UI: {l}")

            # Update overlay status
            while True:
                cmd = proc.stdout.readline()[:-1]
                if not cmd:
                    break
                if cmd.startswith("stat:"):
                    status = cast(Status, cmd[5:])
                    if status == "closed":
                        if shown:
                            hide_hhd(disp, hhd, steam, old)
                            old = None
                            writer.reset()
                            # Prevent grabbing when the UI is not shown
                            emit.grab(False)
                        shown = False
                    else:
                        if not shown:
                            if steam:
                                old, _ = update_steam_values(disp, steam, None)
                            show_hhd(disp, hhd, steam)
                            writer.reset()
                        shown = True
                elif cmd.startswith("grab:"):
                    enable = cmd[5:]
                    emit.grab(enable == "enable")

            # Sleep a bit to avoid running too often
            # Only do so if the earlier sleep was too short to avoid having
            # steam slipping in the UI and flashing the screen
            elapsed = time.perf_counter() - start
            if elapsed < LOOP_SLEEP:
                time.sleep(LOOP_SLEEP - elapsed)
    except Exception as e:
        logger.warning(f"The overlay process ended with an exception:\n{e}")
    finally:
        logger.info(f"Stopping overlay process.")
        try:
            writer.write("cmd:close\n")
            time.sleep(0.2)
        except Exception as e:
            logger.error(f"Error informing overlay:\n{e}")
        proc.kill()
        proc.wait()
        emit.grab(False)
        if wake_handler:
            wake_handler.close()
        # Make sure we leave on the active state
        standby_transition("active")


class OverlayService:
    def __init__(self, ctx: Context, emit: Emitter) -> None:
        self.ctx = ctx
        self.started = False
        self.t = None
        self.should_exit = None
        self.emit = emit
        self.proc = None
        self.interceptionSupported = True
        self.last_check = None
        self.installed = True
        self.gsconf = Config()

    def launch_overlay(self):
        if not self.installed:
            return
        curr = time.perf_counter()
        if self.last_check and curr - self.last_check < OVERLAY_CHECK_INTERVAL:
            return
        self.last_check = curr

        launched = self._open_overlay(requested=False)
        if launched and not self.is_healthy():
            self.started = False

    def _open_overlay(self, requested=False):
        # Should not be called by outsiders
        # requires special permissions and error handling by update
        if self.started or not self.installed:
            return True

        displays = get_gamescope_displays()
        if not displays:
            if requested:
                logger.warning(
                    "Could not find overlay displays, gamescope is not active."
                )
            return False
        if requested:
            logger.debug(f"Found the following gamescope displays: {displays}")

        res = get_overlay_display(displays, self.ctx)
        if not res:
            if requested:
                logger.error(
                    f"Could not find overlay display in gamescope displays. This should never happen."
                )
            return False

        logger.info("Attempting to launch overlay.")

        exe = find_overlay_exe(self.ctx)
        if not exe:
            logger.warning("Overlay is not installed, not launching.")
            self.installed = False
            return False
        logger.info(f"Found overlay executable '{exe}'")
        disp, name = res
        logger.debug(f"Overlay display is the following: DISPLAY={name}")

        self.proc = inject_overlay(exe, name, self.ctx)
        self.writer = OverlayWriter(self.proc.stdin, mute=self.interceptionSupported)
        self.emit.register_intercept(self.writer)
        self.should_exit = TEvent()
        self.t = Thread(
            target=loop_manage_overlay,
            args=(
                disp,
                self.proc,
                self.emit,
                self.writer,
                self.should_exit,
                requested,
                self.gsconf,
            ),
        )
        self.t.start()

        self.started = True
        logger.info("Overlay launched.")
        return True

    def _open_de(self):
        # Allow opening the overlay in desktop
        # wayland only, somewhat hardcoded.
        if self.started:
            return True

        # Launch the overlay
        auth = find_x11_auth(self.ctx)
        if not auth:
            logger.warning("Could not find X11 authority file.")
            return False
        logger.info(f"Found X11 authority file:\n'{auth}'")
        disp = find_x11_display(self.ctx)
        if not disp:
            logger.warning(
                "Tried to find a wayland display to launch the overlay as an application and could not find it."
            )
            return False
        logger.info(f"Launching hhd-ui in display: {disp}")
        exe = find_overlay_exe(self.ctx)
        if not exe:
            return False
        self.proc = launch_overlay_de(exe, disp, auth, self.ctx)

        # Start a managing thread
        self.writer = OverlayWriter(self.proc.stdin, mute=self.interceptionSupported)
        self.emit.register_intercept(self.writer)
        self.should_exit = TEvent()
        self.t = Thread(
            target=loop_manage_desktop,
            args=(self.proc, self.emit, self.writer, self.should_exit),
        )
        self.t.start()
        self.started = True
        self.started_de = True

        return self.proc.poll() is None

    def close(self):
        if self.should_exit and self.t:
            self.should_exit.set()
            self.t.join()
        self.should_exit = None
        self.t = None
        self.started = False

    def is_healthy(self):
        if not self.t or not self.should_exit:
            logger.error("'is_healthy' called before 'start'")
            return False

        if not self.t.is_alive():
            logger.error("Overlay thread died")
            return False

        return True

    def update(self, cmd: Command, init: bool):
        # Accessing the user's display requires the user's priviledges
        if not self.started and not init:
            # This function is called with QAM single presses and guide presses
            # do not initialize for those.
            return
        try:
            ret = self._open_overlay()
            if not ret:
                self._open_de()
            if not self.is_healthy():
                logger.warning(f"Overlay service died, attempting to restart.")
                self.close()

                ret = self._open_overlay()
                if not ret:
                    ret = self._open_de()
                if not ret:
                    logger.error("Failed to start hhd-ui.")
                return

            if not self.proc:
                logger.error("Overlay subprocess is null. Should never happen.")
                return

            self.writer.write(f"\ncmd:{cmd}\n")
        except Exception as e:
            logger.error(f"Failed launching overlay with error:\n{e}")
            self.close()

    def notify(self, events):
        if not SUPPORTS_STANDBY:
            return
        if not self.gsconf or not self.gsconf.get("dpms", False):
            return
        
        for ev in events:
            if ev.get("type", None) != "special":
                continue
            if ev.get("event", None) != "pbtn_short":
                continue
            
            # If steam does not suspend us the following breaks:
            # # Fire screen_off while the powerbutton event is happening
            # logger.info("Powerbutton event detected, transitioning to standby.")
            # standby_transition("screen_off")