import logging
import os
import subprocess
from typing import Literal

logger = logging.getLogger(__name__)


class WakeHandler:
    def __init__(
        self,
        who: str = "HandheldDaemon",
        why: str = "Handheld Daemon: Turn off display",
    ) -> None:
        self.who = who
        self.why = why
        self.proc: subprocess.Popen[str] | None = None
        self.inhibitor: subprocess.Popen[str] | None = None
        self.broken = False
        self.fd = -1
        self.got_prepare = False

    def start(self):
        try:
            self.proc = subprocess.Popen(
                [
                    "dbus-monitor",
                    "--system",
                    "type='signal',interface='org.freedesktop.login1.Manager'",
                    "--monitor",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
            assert self.proc.stdout is not None
            self.fd = self.proc.stdout.fileno()
            os.set_blocking(self.fd, False)

            if not self.inhibit(True):
                self.close()
                return False

            return True
        except Exception:
            if self.proc:
                self.proc.terminate()
                self.proc.wait()
            self.proc = None
            self.broken = True
            return False

    def inhibit(self, enable: bool):
        if self.inhibitor:
            self.inhibitor.terminate()
            self.inhibitor.wait()
            self.inhibitor = None

        if self.broken:
            return False

        if enable:
            try:
                self.inhibitor = subprocess.Popen(
                    [
                        "systemd-inhibit",
                        "--what=sleep",
                        "--mode=delay",
                        "--who",
                        self.who,
                        "--why",
                        self.why,
                        "--",
                        "tail",
                        "-f",
                        "/dev/null",
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    text=True,
                )
                return True
            except Exception:
                self.inhibitor = None
                return False

        return True

    def __call__(self) -> Literal["entry", "exit", None]:
        if self.broken or self.fd == -1 or not self.proc or not self.proc.stdout:
            return None
        try:
            while line := self.proc.stdout.readline():
                if "PrepareForSleep" in line:
                    self.got_prepare = True
                elif self.got_prepare and "boolean" in line:
                    self.got_prepare = False
                    return "entry" if "true" in line else "exit"
        except Exception as e:
            logger.error(f"Systemd monitor error:\n{e}")
            self.close()
            self.broken = True

        return None

    def close(self):
        if self.proc:
            self.proc.kill()
            self.proc.wait()
        self.proc = None
        self.fd = -1
        self.inhibit(False)
