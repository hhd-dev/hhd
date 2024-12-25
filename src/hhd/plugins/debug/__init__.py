import logging
import os
import subprocess
import sys
from threading import Event, Thread
from typing import Sequence

from hhd.i18n import _
from hhd.plugins import Context, HHDPlugin, HHDSettings, load_relative_yaml
from hhd.plugins.conf import Config
from hhd.utils import GIT_ADJ, GIT_HHD, HHD_DEV_DIR

from .logs import get_log

logger = logging.getLogger(__name__)

FPASTE_SERVICE = os.environ.get("HHD_FPASTE", "fpaste")
BUGREPORTS_ENABLED = os.environ.get("HHD_BUGREPORT", "0") == "1"
USES_BETA = os.environ.get("HHD_SWITCH_ROOT", "0") == "1"


def prepare_hhd_dev(ev):
    try:
        os.makedirs(HHD_DEV_DIR, exist_ok=True)
        subprocess.run(
            ["python3", "-m", "venv", "--system-site-packages", HHD_DEV_DIR], check=True
        )
        subprocess.run(
            [
                f"{HHD_DEV_DIR}/bin/pip",
                "install",
                "--upgrade",
                "--cache-dir",
                "/tmp/__hhd_update_cache",
                GIT_HHD,
                GIT_ADJ,
            ],
            check=True,
        )
    except Exception as e:
        ev.set()
        # Show full stacktrace
        raise e


def upload_log(boot: str, out: dict):
    match boot:
        case "current":
            bootnum = 0
        case "previous":
            bootnum = -1
        case "m2":
            bootnum = -2
        case "m3":
            bootnum = -3
        case _:
            bootnum = 0

    logs = get_log(bootnum)
    try:
        res = subprocess.run(
            [FPASTE_SERVICE, "-x", str(72 * 60)],
            input=logs,
            check=True,
            capture_output=True,
            text=True,
        )
        if res.returncode != 0:
            raise Exception(f"fpaste failed with code {res.returncode}")
        
        out["url"] = res.stdout.strip()
        out["error"] = None
    except Exception as e:
        logger.error("Failed to upload logs to fpaste: %s", e)
        out["url"] = None
        out["error"] = str(e)


class DebugPlugin(HHDPlugin):
    def __init__(self) -> None:
        self.name = f"debug"
        self.priority = 80
        self.log = "DDBG"
        self.emit = None
        self.t = None
        self.error = None
        self.fpaste_t = None
        self.fpaste_data = None

    def settings(self) -> HHDSettings:
        sets = {"debug": load_relative_yaml("settings.yml")}
        if not USES_BETA:
            del sets["debug"]["dev"]["children"]["hhd_dev_exit"]
        return sets

    def open(
        self,
        emit,
        context: Context,
    ):
        self.emit = emit

    def update(self, conf: Config):
        self._hhd_dev(conf)
        self._fpaste(conf)

    def _fpaste(self, conf: Config):
        fpaste = conf.get_action("debug.reports.submit")

        if self.fpaste_t:
            if self.fpaste_t.is_alive():
                return
            self.fpaste_t.join()
            self.fpaste_t = None
            if self.fpaste_data and self.fpaste_data.get("url", None):
                conf["debug.reports.url"] = self.fpaste_data["url"]
            elif self.fpaste_data and self.fpaste_data.get("error", None):
                conf["debug.reports.error"] = self.fpaste_data["error"]
            conf["debug.reports.progress"] = None
        elif fpaste:
            conf["debug.reports.progress"] = {
                "text": _("Uploading log to fpaste..."),
                "value": None,
                "unit": None,
            }
            conf["debug.reports.url"] = None
            conf["debug.reports.error"] = None
            self.fpaste_data = {}
            self.fpaste_t = Thread(
                target=upload_log,
                args=(conf.get("debug.reports.boot", "current"), self.fpaste_data),
            )
            self.fpaste_t.start()

    def _hhd_dev(self, conf: Config):
        hhd_dev = conf.get_action("debug.dev.hhd_dev")

        if USES_BETA and self.emit and conf.get_action("debug.dev.hhd_dev_exit"):
            conf["debug.dev.progress"] = {
                "text": _("Shutting down..."),
                "value": None,
                "unit": None,
            }
            self.emit({"type": "special", "event": "shutdown_dev"})

        if self.t:
            if self.t.is_alive():
                return
            self.t.join()
            self.t = None
            if self.error and self.error.is_set():
                conf["debug.dev.progress"] = None
                conf["debug.dev.error"] = _("Failed to download Handheld Daemon Beta.")
            elif self.emit:
                self.emit({"type": "special", "event": "restart_dev"})

        if hhd_dev:
            conf["debug.dev.progress"] = {
                "text": _("Downloading Beta and Restarting..."),
                "value": None,
                "unit": None,
            }
            self.error = Event()
            self.t = Thread(target=prepare_hhd_dev, args=(self.error,))
            self.t.start()

    def close(self):
        if self.t:
            self.t.join()
            self.t = None
        if self.fpaste_t:
            self.fpaste_t.join()
            self.fpaste_t = None


def autodetect(existing: Sequence[HHDPlugin]) -> Sequence[HHDPlugin]:
    if len(existing):
        return existing

    if not BUGREPORTS_ENABLED:
        return []

    return [DebugPlugin()]
