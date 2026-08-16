import glob
import logging
import time
from threading import Event

from hhd.plugins import Emitter
from hhd.plugins.systemd import WakeHandler

from .cec import (
    CEC_MSG_ACTIVE_SOURCE,
    CecState,
    initialize_cec,
    receive_cec,
    uninitialize,
)
from .remote import TvRemote

logger = logging.getLogger(__name__)

SCAN_INTERVAL = 2.0
RETRY_INTERVAL = 10.0
LOOP_INTERVAL = 0.05


class CecService:
    def __init__(self, should_exit: Event, emit: Emitter | None = None):
        self.should_exit = should_exit
        self.adapters: dict[str, CecState] = {}
        self.retry_after: dict[str, float] = {}
        self.suspended = False
        self.next_scan = 0.0
        self.remote = TvRemote(emit)
        self.sleep = WakeHandler(
            why="Handheld Daemon: Restore HDMI-CEC state before sleep"
        )

    def _close_adapter(self, path: str):
        state = self.adapters.pop(path, None)
        self.remote.reset()
        try:
            if state:
                uninitialize(state)
        except Exception as e:
            logger.warning(f"Could not cleanly close CEC adapter '{path}': {e}")

    def _close_adapters(self):
        for path in list(self.adapters):
            self._close_adapter(path)

    def scan(self):
        paths = set(glob.glob("/dev/cec*"))
        now = time.monotonic()
        for path in set(self.retry_after) - paths:
            del self.retry_after[path]
        for path in set(self.adapters) - paths:
            logger.info(f"CEC adapter '{path}' disappeared.")
            self._close_adapter(path)

        for path in sorted(paths - set(self.adapters)):
            if now < self.retry_after.get(path, 0.0):
                continue
            try:
                state = initialize_cec(path)
                self.adapters[path] = state
                try:
                    self.remote.open()
                except Exception as e:
                    logger.warning(f"Could not create TV Remote input device: {e}")
                self.retry_after.pop(path, None)
                logger.info(
                    f"Activated CEC adapter '{path}' at physical address "
                    f"{state.phys_addr >> 12:x}."
                    f"{state.phys_addr >> 8 & 0xf:x}."
                    f"{state.phys_addr >> 4 & 0xf:x}."
                    f"{state.phys_addr & 0xf:x}."
                )
            except Exception as e:
                logger.warning(f"Could not activate CEC adapter '{path}': {e}")
                self.retry_after[path] = now + RETRY_INTERVAL

    def receive(self):
        for path, state in list(self.adapters.items()):
            try:
                for _ in range(32):
                    msg = receive_cec(state)
                    if msg is None:
                        break
                    if msg.msg[1] == CEC_MSG_ACTIVE_SOURCE and msg.len >= 4:
                        active = (int(msg.msg[2]) << 8) | int(msg.msg[3])
                        state.active = active == state.phys_addr
                    if int(msg.msg[0]) & 0xF == state.logical_addr:
                        self.remote.handle(msg)
            except OSError as e:
                logger.warning(f"Could not receive from CEC adapter '{path}': {e}")
                self._close_adapter(path)
                self.retry_after[path] = time.monotonic() + RETRY_INTERVAL

    def _sleep_transition(self):
        transition = self.sleep()
        if transition == "entry" and not self.suspended:
            logger.info("Restoring HDMI-CEC state before sleep.")
            self._close_adapters()
            self.suspended = True
            self.sleep.inhibit(False)
        elif transition == "exit" and self.suspended:
            logger.info("Reinitializing HDMI-CEC state after resume.")
            self.suspended = False
            self.sleep.inhibit(True)
            self.retry_after.clear()
            self.next_scan = 0.0

    def run(self):
        if not self.sleep.start():
            logger.error("Could not start HDMI-CEC sleep handler.")
        try:
            while not self.should_exit.wait(LOOP_INTERVAL):
                self._sleep_transition()
                now = time.monotonic()
                if not self.suspended and now >= self.next_scan:
                    self.next_scan = now + SCAN_INTERVAL
                    self.scan()
                if not self.suspended:
                    self.receive()
                    self.remote.tick(now)
        finally:
            self._close_adapters()
            self.remote.close()
            self.sleep.close()


def cec_run(should_exit: Event, emit: Emitter | None = None):
    CecService(should_exit, emit).run()
