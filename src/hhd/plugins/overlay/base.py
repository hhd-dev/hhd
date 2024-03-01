import logging
import select
import subprocess
import time
from threading import Event as TEvent
from threading import Thread
from typing import Literal, cast

from Xlib import display

from hhd.plugins import Context
from hhd.utils import restore_priviledge, switch_priviledge

from .overlay import find_overlay_exe, inject_overlay
from .x11 import (
    find_hhd,
    find_steam,
    get_gamescope_displays,
    get_overlay_display,
    hide_hhd,
    is_steam_shown,
    prepare_hhd,
    show_hhd,
)

logger = logging.getLogger(__name__)
Command = Literal["close", "open_qam", "open_expanded", "open_notification"]
Status = Literal["closed", "qam", "expanded", "notification"]

GUARD_CHECK = 0.5
STARTUP_MAX_DELAY = 10
LOOP_SLEEP = 0.1


def update_status(proc: subprocess.Popen, cmd: Command):
    if not proc.stdin:
        logger.warning(f"Could not update overlay because stdin not found.")
        return False

    try:
        proc.stdin.write(f"\ncmd:{cmd}\n")
        proc.stdin.flush()
        return True
    except Exception as e:
        logger.warning(f"Could not update overlay status with error:\n{e}")
        return False


def loop_manage_overlay(
    disp: display.Display, proc: subprocess.Popen, should_exit: TEvent
):
    try:
        status: Status = "closed"

        assert proc.stderr and proc.stdout

        fd_out = proc.stdout.fileno()
        fd_err = proc.stderr.fileno()

        # Give electron time to warmup
        start = time.perf_counter()
        curr = start
        while (
            curr - start < STARTUP_MAX_DELAY
            and not find_hhd(disp)
            and not should_exit.is_set()
        ):
            time.sleep(GUARD_CHECK)
            curr = time.perf_counter()

        hhd = find_hhd(disp)
        steam = find_steam(disp)
        old = None
        shown = False

        if hhd:
            logger.info(f"UI window found in gamescope, starting handler.")
            prepare_hhd(disp, hhd)

        while not should_exit.is_set():
            if not hhd:
                logger.error(f"UI Window not found, exitting overlay.")
                break
            if not steam:
                logger.error(f"Steam window not found, exitting overlay.")
                break

            r, _, _ = select.select([fd_out, fd_err], [], [], GUARD_CHECK)

            if proc.poll() is not None:
                logger.warning(f"Overlay stopped (steam may have restarted). Closing.")
                return

            if shown and is_steam_shown(disp, steam):
                logger.warning(
                    f"Steam overlay shown while hhd-ui is active. Hiding UI to avoid issues."
                )
                hide_hhd(disp, hhd, steam, None)
                shown = False

            if fd_err in r:
                l = proc.stderr.readline()[:-1]
                if l:
                    logger.info(f"UI: {l}")

            if fd_out in r:
                cmd = proc.stdout.readline()[:-1]
                if cmd.startswith("stat:"):
                    status = cast(Status, cmd[5:])
                    if status == "closed":
                        if shown:
                            hide_hhd(disp, hhd, steam, old)
                        shown = False
                    else:
                        if not shown:
                            old = show_hhd(disp, hhd, steam)
                        shown = True

            # Sleep a bit to avoid waking up too much
            time.sleep(LOOP_SLEEP)
    finally:
        logger.info(f"Stopping overlay process.")
        proc.kill()
        proc.wait()


class OverlayService:
    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx
        self.started = False
        self.t = None
        self.should_exit = None

    def _start(self):
        # Should not be called by outsiders
        # requires special permissions and error handling by update
        if self.started:
            return True
        logger.info("Attempting to launch overlay.")

        exe = find_overlay_exe()
        if not exe:
            logger.warning("Overlay is not installed, not launching.")
            return False
        logger.info(f"Found overlay executable '{exe}'")

        displays = get_gamescope_displays()
        if not displays:
            logger.warning("Could not find overlay displays, gamescope is not active.")
            return False
        logger.debug(f"Found the following gamescope displays: {displays}")

        res = get_overlay_display(displays)
        if not res:
            logger.error(
                f"Could not find overlay display in gamescope displays. This should never happen."
            )
            return False
        disp, name = res
        logger.debug(f"Overlay display is the folling: DISPLAY={name}")

        self.proc = inject_overlay(exe, name, self.ctx)
        self.should_exit = TEvent()
        self.t = Thread(
            target=loop_manage_overlay, args=(disp, self.proc, self.should_exit)
        )
        self.t.start()

        self.started = True
        logger.info("Overlay launched.")
        return True

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
        old = switch_priviledge(self.ctx, False)
        try:
            if not self._start():
                return
            if not self.is_healthy():
                logger.warning(f"Overlay service died, attempting to restart.")
                self.close()
                if not self._start():
                    logger.warning(f"Restarting overlay failed.")
                    return

            if not self.proc:
                logger.error("Overlay subprocess is null. Should never happen.")
                return

            update_status(self.proc, cmd)
        except Exception as e:
            logger.error(f"Failed launching overlay with error:\n{e}")
            self.close()
        finally:
            restore_priviledge(old)
