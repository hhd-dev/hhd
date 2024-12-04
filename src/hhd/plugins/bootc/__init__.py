import json
import logging
import os
import subprocess
from typing import Literal, Sequence

from hhd.i18n import _
from hhd.plugins import Context, HHDPlugin, HHDSettings, load_relative_yaml
from hhd.plugins.conf import Config

logger = logging.getLogger(__name__)

BOOTC_ENABLED = os.environ.get("HHD_BOOTC", "0") == "1"
BOOTC_PATH = os.environ.get("HHD_BOOTC_PATH", "bootc")
BRANCHES = os.environ.get(
    "HHD_BOOTC_BRANCHES", "stable:Stable,testing:Testing,unstable:Unstable"
)

BOOTC_STATUS_CMD = [
    BOOTC_PATH,
    "status",
    "--format",
    "json",
]

RPM_OSTREE_RESET = [
    "rpm-ostree",
    "reset",
]

BOOTC_CHECK_CMD = [
    BOOTC_PATH,
    "update",
    "--check",
]

BOOTC_ROLLBACKCMD = [
    BOOTC_PATH,
    "rollback",
]

BOOTC_UPDATE_CMD = [
    BOOTC_PATH,
    "update",
]

SKOPEO_REBASE_CMD = lambda ref: ["skopeo", "inspect", ref]


STAGES = Literal[
    "init",
    "ready",
    "ready_check",
    "ready_updated",
    "incompatible",
    "waiting",
    "rebase_dialog",
    "rollback_dialog",
    "download_loading",
    "download_error",
    "download_complete",
    "waiting_progress",
]


def get_bootc_status():
    try:
        output = subprocess.check_output(BOOTC_STATUS_CMD).decode("utf-8")
        return json.loads(output)
    except Exception as e:
        logger.error(f"Failed to get bootc status: {e}")
        return {}


def get_ref_from_status(status: dict | None):
    return (status or {}).get("spec", {}).get("image", {}).get("image", "")


def get_branch(ref: str, branches: dict):
    curr_tag = ref[ref.rindex(":") + 1 :]
    for branch in branches:
        if branch in curr_tag:
            curr_tag = branch
            break
    return next(iter(branches))


def get_rebase_refs(ref: str, lim: int = 5, branches: dict = {}):
    try:
        output = subprocess.check_output(SKOPEO_REBASE_CMD(ref)).decode("utf-8")
        data = json.loads(output)

        curr_tag = get_branch(ref, branches) or ref

        versions = data.get("RepoTags", [])
        same_branch = [v for v in versions if curr_tag in v]
        same_branch.sort(reverse=True)
        return same_branch[:lim]

    except Exception as e:
        logger.error(f"Failed to get rebase refs: {e}")
        return []


def run_command_threaded(cmd: list, output: bool = False):
    try:
        return subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE if output else None,
        )
    except Exception as e:
        logger.error(f"Failed to run command: {e}")


def is_incompatible(status: dict):
    if status.get("apiVersion", None) != "org.containers.bootc/v1":
        return True

    if ((status.get("status", None) or {}).get("booted", None) or {}).get(
        "incompatible", False
    ):
        return True

    return False


class BootcPlugin(HHDPlugin):
    def __init__(self) -> None:
        self.name = f"bootc"
        self.priority = 85
        self.log = "bupd"
        self.proc = None

        self.branches = {}
        for branch in BRANCHES.split(","):
            name, display = branch.split(":")
            self.branches[name] = display

        self.status = None
        self.enabled = True
        self.state: STAGES = "init"

    def settings(self) -> HHDSettings:
        if self.enabled:
            sets = {"updates": {"bootc": load_relative_yaml("settings.yml")}}

            sets["updates"]["bootc"]["children"]["stage"]["modes"]["rebase"][
                "children"
            ]["branch"]["options"] = self.branches

            return sets
        else:
            return {}

    def open(
        self,
        emit,
        context: Context,
    ):
        self.updated = False

    def get_version(self, s):
        assert self.status
        return (
            (self.status.get("status", {}).get(s, None) or {})
            .get("image", {})
            .get("version", "")
        )

    def _init(self, conf: Config):
        self.status = get_bootc_status()
        img = self.status.get("spec", {}).get("image", {}).get("image", "")
        if "/" in img:
            img = img[img.rfind("/") + 1 :]
        if img:
            conf["updates.bootc.image"] = img

        for v in ["staged", "booted", "rollback"]:
            conf[f"updates.bootc.{v}"] = self.get_version(v)

        conf["updates.bootc.status"] = ""
        self.updated = True

        cached = self.status.get("status", {}).get("booted", {}).get("cachedUpdate", {})
        cached_version = cached.get("version", "") if cached else ""
        cached_img = cached.get("image", {}).get("image", "") if cached else ""
        if "/" in cached_img:
            cached_img = cached_img[cached_img.rfind("/") + 1 :]

        if is_incompatible(self.status):
            conf["updates.bootc.stage.mode"] = "incompatible"
            self.state = "incompatible"
            conf[f"updates.bootc.update"] = None
        elif (
            cached_version
            and cached_img == img
            and cached_version != self.get_version("staged")
        ):
            conf["updates.bootc.stage.mode"] = "ready"
            self.state = "ready"
            conf[f"updates.bootc.update"] = cached_version
        elif self.get_version("staged"):
            conf["updates.bootc.stage.mode"] = "ready_updated"
            self.state = "ready_updated"
            conf[f"updates.bootc.update"] = None
        else:
            conf["updates.bootc.stage.mode"] = "ready_check"
            self.state = "ready_check"
            conf[f"updates.bootc.update"] = None

    def update(self, conf: Config):

        # Try to fill in basic info
        match self.state:
            case "init":
                self._init(conf)
            # Ready
            case "ready" | "ready_check" | "ready_updated" as e:
                update = conf.get_action(f"updates.bootc.stage.{e}.update")
                revert = conf.get_action(f"updates.bootc.stage.{e}.revert")
                rebase = conf.get_action(f"updates.bootc.stage.{e}.rebase")
                rollback = conf.get_action(f"updates.bootc.stage.{e}.rollback")
                reboot = conf.get_action(f"updates.bootc.stage.{e}.reboot")

                if update:
                    if e == "ready":
                        self.state = "waiting_progress"
                        self.proc = run_command_threaded(BOOTC_UPDATE_CMD, output=False)
                        conf["updates.bootc.stage.mode"] = "loading"
                        conf["updates.bootc.stage.loading.progress"] = {
                            "text": _("Updating... "),
                            "value": None,
                            "unit": None,
                        }
                    else:
                        self.state = "waiting"
                        self.proc = run_command_threaded(BOOTC_STATUS_CMD)
                        conf["updates.bootc.stage.mode"] = "loading"
                        conf["updates.bootc.stage.loading.progress"] = {
                            "text": _("Checking for updates..."),
                            "value": None,
                            "unit": None,
                        }
                elif revert:
                    self.state = "waiting"
                    self.proc = run_command_threaded(BOOTC_ROLLBACKCMD)
                    conf["updates.bootc.stage.mode"] = "loading"
                    conf["updates.bootc.stage.loading.progress"] = {
                        "text": (
                            _("Undoing Update...")
                            if e == "ready_updated"
                            else _("Setting Previous as default...")
                        ),
                        "value": None,
                        "unit": None,
                    }
                elif rebase:
                    if not self.branches:
                        self._init(conf)
                    else:
                        self.state = "rebase_dialog"
                        conf["updates.bootc.stage.mode"] = "rebase"
                        # Get branch that should be default
                        curr = (
                            (self.status or {})
                            .get("spec", {})
                            .get("image", {})
                            .get("image", "")
                        )
                        default = get_branch(curr, self.branches) or next(
                            iter(self.branches)
                        )
                        conf["updates.bootc.stage.rebase.branch"] = default
                elif reboot:
                    logger.info("User pressed reboot in updater. Rebooting...")
                    subprocess.run(["systemctl", "reboot"])

            # Incompatible
            case "incompatible":
                if conf.get_action("updates.bootc.stage.incompatible.reset"):
                    self.state = "waiting_progress"
                    self.proc = run_command_threaded(RPM_OSTREE_RESET, output=False)
                    conf["updates.bootc.stage.mode"] = "loading"
                    conf["updates.bootc.stage.loading.progress"] = {
                        "text": _("Removing Customizations..."),
                        "value": None,
                        "unit": None,
                    }

            # Rebase dialog
            case "rebase_dialog":
                apply = conf.get_action("updates.bootc.stage.rebase.apply")
                cancel = conf.get_action("updates.bootc.stage.rebase.cancel")

                if cancel:
                    self._init(conf)
                elif apply:
                    branch = conf.get("updates.bootc.stage.rebase.branch", None)

                    curr = get_ref_from_status(self.status)
                    if curr == branch:
                        self._init(conf)
                    elif curr and branch in self.branches:
                        # remove tag from curr and replace with branch
                        next_ref = (
                            (curr[: curr.rindex(":")] if ":" in curr else curr)
                            + ":"
                            + branch
                        )

                        self.state = "waiting"
                        self.proc = run_command_threaded(
                            [BOOTC_PATH, "switch", next_ref]
                        )
                        conf["updates.bootc.stage.mode"] = "loading"
                        conf["updates.bootc.stage.loading.progress"] = {
                            "text": _("Rebasing to "),
                            "unit": self.branches.get(branch, branch),
                            "value": None,
                        }
                    else:
                        self._init(conf)

            # Wait for the subcommand to complete
            case "waiting_progress":
                if self.proc is None:
                    self._init(conf)
                elif self.proc.poll() is not None:
                    self._init(conf)
                    self.proc = None
            case "waiting":
                if self.proc is None:
                    self._init(conf)
                elif self.proc.poll() is not None:
                    self._init(conf)
                    self.proc = None

    def close(self):
        pass


def autodetect(existing: Sequence[HHDPlugin]) -> Sequence[HHDPlugin]:
    if len(existing):
        return existing

    if not BOOTC_ENABLED:
        return []

    return [BootcPlugin()]
