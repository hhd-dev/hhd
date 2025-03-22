import json
import logging
import os
import select
import signal
import subprocess
import shutil
import time
from threading import Lock, Thread
from typing import Literal, Sequence

from hhd.i18n import _
from hhd.plugins import Context, HHDPlugin, HHDSettings, load_relative_yaml
from hhd.plugins.conf import Config

logger = logging.getLogger(__name__)

REFRESH_HZ = 3
PROGRESS_STAGES = {
    "pulling": (_("Downloading:"), 0, 80),
    "importing": (_("Importing:"), 80, 10),
    "staging": (_("Deploying:"), 90, 10),
    "unknown": (_("Loading"), 100, 0),
}

BOOTC_ENABLED = os.environ.get("HHD_BOOTC", "0") == "1"
BOOTC_PATH = os.environ.get("HHD_BOOTC_PATH", "bootc")
BRANCHES = os.environ.get(
    "HHD_BOOTC_BRANCHES", "stable:Stable,testing:Testing,unstable:Unstable"
)

REF_PREFIX = "§ "
DEFAULT_PREFIX = "◉ "

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

RPM_OSTREE_UPDATE = [
    "rpm-ostree",
    "update",
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

SKOPEO_REBASE_CMD = lambda ref: ["skopeo", "inspect", "docker://" + ref]


STAGES = Literal[
    "init",
    "ready",
    "ready_check",
    "ready_updated",
    "ready_reverted",
    "ready_rebased",
    "incompatible",
    "rebase_dialog",
    "loading",
    "loading_rebase",
    "loading_cancellable",
]


def get_bootc_status():
    try:
        output = subprocess.check_output(BOOTC_STATUS_CMD).decode("utf-8")
        return json.loads(output)
    except Exception as e:
        logger.error(f"Failed to get bootc status: {e}")
        return {}


def get_ref_from_status(status: dict | None):
    return (((status or {}).get("spec", None) or {}).get("image", None) or {}).get(
        "image", ""
    )


def get_branch(ref: str, branches: dict, fallback: bool = True):
    if ":" not in ref:
        return next(iter(branches))
    curr_tag = ref[ref.rindex(":") + 1 :]

    for branch in branches:
        if branch in curr_tag:
            return branch

    if not fallback:
        return None
    # If no tag, assume it is the first one
    return next(iter(branches))


def get_rebase_refs(ref: str, tags, lim: int = 7, branches: dict = {}):
    logger.info(f"Getting rebase refs for {ref}")
    try:
        output = subprocess.check_output(SKOPEO_REBASE_CMD(ref)).decode("utf-8")
        data = json.loads(output)
        versions = data.get("RepoTags", [])

        for branch in branches:
            same_branch = [v for v in versions if v.startswith(branch) and v != branch]
            same_branch.sort(reverse=True)
            tags[branch] = same_branch[:lim]

        logger.info(f"Finished getting refs")
    except Exception as e:
        logger.error(f"Failed to get rebase refs: {e}")


def run_command_threaded(cmd: list):
    try:
        return subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
        )
    except Exception as e:
        logger.error(f"Failed to run command: {e}")


def _bootc_progress_reader(fd, emit, friendly, lock, obj):
    last_update = 0
    try:
        while select.select([fd.fileno()], [], [])[0]:
            data = fd.readline()
            if not data:
                break
            data = json.loads(data)

            text, start, length = PROGRESS_STAGES.get(
                data.get("task", "unknown"), PROGRESS_STAGES["unknown"]
            )

            match data["type"]:
                case "ProgressSteps":
                    curr = data.get("steps", 0)
                    total = data.get("stepsTotal", 0)
                    value = start + min(length, int((curr / (total + 1)) * length))
                    if total > 1:
                        unit = f" {friendly} ({min(curr + 1, total)}/{total})"
                    else:
                        unit = f" {friendly}"
                case "ProgressBytes":
                    curr = data.get("bytes", 0)
                    total = data.get("bytesTotal", 0)
                    value = start + min(length, int((curr / total) * length))
                    unit = f" {friendly} ({curr/1e9:.1f}/{total/1e9 + 0.099:.1f} GB)"
                case _:
                    continue

            with lock:
                obj.update({"text": text, "value": value, "unit": unit})

            # Increase the update rate of the UI
            curr = time.perf_counter()
            if curr - last_update > 1 / REFRESH_HZ and emit:
                last_update = curr
                emit({"type": "special", "event": "refresh"})
    finally:
        fd.close()


def run_command_threaded_progress(cmd: list, emit, friendly, lock):
    r = None
    try:
        r, w = os.pipe2(0)
        proc = subprocess.Popen(
            cmd + [f"--json-fd", str(w), "--quiet"],
            pass_fds=[w],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        os.close(w)

        obj = {}
        fd = os.fdopen(r, "r")
        t = Thread(target=_bootc_progress_reader, args=(fd, emit, friendly, lock, obj))
        t.start()
        return proc, obj
    except Exception as e:
        logger.error(f"Failed to run command: {e}")
        if r:
            os.close(r)
        return None, None


def is_incompatible(status: dict):
    if status.get("apiVersion", None) != "org.containers.bootc/v1":
        return True

    boot_incompatible = (
        (status.get("status", None) or {}).get("booted", None) or {}
    ).get("incompatible", False)

    if staged := ((status.get("status", None) or {}).get("staged", None) or {}):
        return staged.get("incompatible", False)

    return boot_incompatible


def has_bootc_progress_support():
    return "--json-fd" in subprocess.check_output(
        [BOOTC_PATH, "upgrade", "--help"]
    ).decode("utf-8")


class BootcPlugin(HHDPlugin):
    def __init__(self) -> None:
        self.name = f"bootc"
        self.priority = 70
        self.log = "bupd"
        self.proc = None
        self.branch_name = None
        self.branch_ref = None
        self.checked_update = False
        self.t = None
        self.t_data = None
        self.progress_lock = Lock()
        self.progress = None
        self.staged = ""
        self.cached_version = ""
        self.emit = None
        self.updating = False

        self.branches = {}
        for branch in BRANCHES.split(","):
            name, display = branch.split(":")
            self.branches[name] = display

        self.status = None
        self.enabled = True
        self.state: STAGES = "init"

    def settings(self) -> HHDSettings:
        sets = {
            "updates": {"bootc": load_relative_yaml("settings.yml")},
            "hhd": {"settings": load_relative_yaml("general.yml")},
        }

        sets["updates"]["bootc"]["children"]["stage"]["modes"]["rebase"][
            "children"
        ]["branch"]["options"] = self.branches

        return sets

    def open(
        self,
        emit,
        context: Context,
    ):
        self.updated = False
        self.bootc_progress = has_bootc_progress_support()
        self.emit = emit
        if self.bootc_progress:
            logger.info("Bootc progress support detected")
        else:
            logger.warning("Bootc progress support not detected")

    def get_version(self, s):
        assert self.status
        return (
            (self.status.get("status", {}).get(s, None) or {}).get("image", None) or {}
        ).get("version", "")

    def _init(self, conf: Config):
        self.status = get_bootc_status()
        self.updating = False

        if is_incompatible(self.status):
            conf["updates.bootc.stage.mode"] = "incompatible"
            self.state = "incompatible"
            conf[f"updates.bootc.update"] = None
            conf[f"updates.bootc.steamos-update"] = "incompatible"
            return

        ref = ((self.status.get("spec", None) or {}).get("image", None) or {}).get(
            "image", ""
        )
        img = ref
        if "/" in img:
            img = img[img.rfind("/") + 1 :]

        # Find branch and replace tag
        branch = get_branch(img, self.branches)
        rebased_ver = None
        self.branch_name = branch
        self.branch_ref = None
        has_rebased = False
        if branch:
            if ":" in img:
                tag = img[img.rindex(":") + 1 :]
                if tag != branch:
                    rebased_ver = tag
                    has_rebased = True
                    self.branch_ref = ref.split(":")[0] + ":" + branch
                img = img[: img.rindex(":") + 1] + branch
        if img:
            conf["updates.bootc.image"] = img

        # If we have a staged update, that will boot first
        self.staged = og = s = self.get_version("staged")
        staged = False
        if s:
            s = DEFAULT_PREFIX + s
            staged = True
        if s and rebased_ver and og in rebased_ver:
            s = REF_PREFIX + s
            # Only apply one start to avoid confusion
            rebased_ver = None
        conf["updates.bootc.staged"] = s

        # Check if the user selected rollback
        # Then that will be the default, provided there is a rollback
        rollback = (
            not staged
            and (self.status.get("spec", None) or {}).get("bootOrder", None)
            == "rollback"
        )
        s = self.get_version("rollback")
        if s and rollback:
            s = DEFAULT_PREFIX + s
        else:
            rollback = False
        conf[f"updates.bootc.rollback"] = s

        # Otherwise, the booted version will be the default
        og = s = self.get_version("booted")
        if s and not rollback and not staged:
            s = DEFAULT_PREFIX + s
        if s and rebased_ver and og in rebased_ver:
            s = REF_PREFIX + s
        conf[f"updates.bootc.booted"] = s

        conf["updates.bootc.status"] = ""
        self.updated = True

        cached = self.status.get("status", {}).get("booted", {}).get("cachedUpdate", {})
        cached_version = cached.get("version", "") if cached else ""
        cached_img = cached.get("image", {}).get("image", "") if cached else ""
        if "/" in cached_img:
            cached_img = cached_img[cached_img.rfind("/") + 1 :]
        self.cached_version = cached_version

        if self.checked_update:
            conf[f"updates.bootc.update"] = _("No update available")
        else:
            conf[f"updates.bootc.update"] = None

        if (
            cached_version
            and cached_img == img
            and cached_version != self.get_version("staged")
        ):
            conf["updates.bootc.stage.mode"] = "ready"
            self.state = "ready"
            conf[f"updates.bootc.update"] = cached_version
            conf[f"updates.bootc.steamos-update"] = "has-update"
        elif self.get_version("staged"):
            conf["updates.bootc.stage.mode"] = "ready_updated"
            self.state = "ready_updated"
            conf[f"updates.bootc.steamos-update"] = "updated"
        elif has_rebased:
            conf["updates.bootc.stage.mode"] = "ready_rebased"
            self.state = "ready_rebased"
            conf[f"updates.bootc.steamos-update"] = "updated"
        elif rollback:
            conf["updates.bootc.stage.mode"] = "ready_reverted"
            self.state = "ready_reverted"
            conf[f"updates.bootc.steamos-update"] = "updated"
        else:
            conf["updates.bootc.stage.mode"] = "ready_check"
            self.state = "ready_check"
            conf[f"updates.bootc.steamos-update"] = "ready"

    def update(self, conf: Config):

        # Detect reset and avoid breaking the UI
        if conf.get("updates.bootc.stage.mode", None) is None:
            self._init(conf)
            return

        # Try to fill in basic info
        match self.state:
            case "init":
                self._init(conf)
            # Ready
            case (
                "ready"
                | "ready_check"
                | "ready_updated"
                | "ready_reverted"
                | "ready_rebased" as e
            ):
                update = conf.get_action(f"updates.bootc.stage.{e}.update")
                revert = conf.get_action(f"updates.bootc.stage.{e}.revert")
                rebase = conf.get_action(f"updates.bootc.stage.{e}.rebase")
                reboot = conf.get_action(f"updates.bootc.stage.{e}.reboot")

                steamos = conf.get("updates.bootc.steamos-update", None)

                # Handle steamos polkit
                if steamos == "check":
                    if not conf.get("hhd.settings.bootc_steamui", True):
                        # Updates are disabled, return that there are none
                        conf["updates.bootc.steamos-update"] = "ready"
                    elif e == "ready":
                        conf["updates.bootc.steamos-update"] = "has-update"
                    elif e == "ready_rebased":
                        # Make sure nothing funny happens on the rebase dialog
                        conf["updates.bootc.steamos-update"] = "ready"
                    else:
                        update = True
                if steamos == "apply":
                    update = True

                if update:
                    if e == "ready_rebased" and self.branch_ref:
                        self.checked_update = False
                        self.state = "loading_cancellable"
                        cmd = [BOOTC_PATH, "switch", self.branch_ref]
                        if self.bootc_progress:
                            self.proc, self.progress = run_command_threaded_progress(
                                cmd,
                                self.emit,
                                self.branch_name,
                                self.progress_lock,
                            )
                        else:
                            self.proc = run_command_threaded(cmd)
                        conf["updates.bootc.stage.mode"] = "loading_cancellable"
                        conf["updates.bootc.stage.loading_cancellable.progress"] = {
                            "text": _("Updating to latest "),
                            "unit": self.branches.get(
                                self.branch_name, self.branch_name
                            ),
                            "value": None,
                        }
                    elif e == "ready":
                        self.state = "loading_cancellable"
                        self.checked_update = False
                        self.updating = True
                        if self.bootc_progress:
                            self.proc, self.progress = run_command_threaded_progress(
                                BOOTC_UPDATE_CMD,
                                self.emit,
                                self.cached_version or self.branch_name or "",
                                self.progress_lock,
                            )
                        else:
                            self.proc = run_command_threaded(BOOTC_UPDATE_CMD)
                        conf["updates.bootc.stage.mode"] = "loading_cancellable"
                        conf["updates.bootc.stage.loading_cancellable.progress"] = {
                            "text": _("Updating... "),
                            "value": None,
                            "unit": None,
                        }
                    else:
                        self.state = "loading"
                        self.proc = run_command_threaded(BOOTC_CHECK_CMD)
                        self.checked_update = True
                        conf["updates.bootc.stage.mode"] = "loading"
                        conf["updates.bootc.stage.loading.progress"] = {
                            "text": _("Checking for updates..."),
                            "value": None,
                            "unit": None,
                        }
                elif revert:
                    self.checked_update = False
                    self.state = "loading"
                    self.proc = run_command_threaded(BOOTC_ROLLBACKCMD)
                    conf["updates.bootc.stage.mode"] = "loading"
                    if e == "ready_updated":
                        text = _("Undoing Update...")
                    elif e == "ready_reverted":
                        text = _("Undoing Revert...")
                    else:
                        text = _("Reverting to Previous version...")
                    conf["updates.bootc.stage.loading.progress"] = {
                        "text": text,
                        "value": None,
                        "unit": None,
                    }
                elif rebase:
                    self.checked_update = False
                    if not self.branches:
                        self._init(conf)
                    else:
                        # Get branch that should be default
                        curr = (
                            (self.status or {})
                            .get("spec", {})
                            .get("image", {})
                            .get("image", "")
                        )
                        default = get_branch(curr, self.branches)
                        conf["updates.bootc.stage.rebase.branch"] = default

                        # Prepare loader
                        conf["updates.bootc.stage.mode"] = "loading"
                        conf["updates.bootc.stage.loading.progress"] = {
                            "text": _("Loading Versions..."),
                            "value": None,
                            "unit": None,
                        }

                        # Launch loader thread
                        self.t_data = {}
                        self.t = Thread(
                            target=get_rebase_refs,
                            args=(curr, self.t_data),
                            kwargs={"branches": self.branches},
                        )
                        self.t.start()
                        self.state = "loading_rebase"
                elif reboot:
                    logger.info("User pressed reboot in updater. Rebooting...")
                    subprocess.run(["systemctl", "reboot"])

            # Incompatible
            case "incompatible":
                if conf.get_action("updates.bootc.stage.incompatible.reset"):
                    self.state = "loading"
                    self.proc = run_command_threaded(RPM_OSTREE_RESET)
                    conf["updates.bootc.stage.mode"] = "loading"
                    conf["updates.bootc.stage.loading.progress"] = {
                        "text": _("Removing Customizations..."),
                        "value": None,
                        "unit": None,
                    }

            # Rebase dialog
            case "rebase_dialog" | "loading_rebase" as e:
                # FIXME: this is the only match statement that
                # does early returns. Allows loading the previous
                # versions instantly.

                conf["updates.bootc.update"] = None
                if e == "loading_rebase":
                    if self.t is None:
                        self._init(conf)
                        return
                    elif not self.t.is_alive():
                        self.t = None
                        self.state = "rebase_dialog"
                        conf["updates.bootc.stage.mode"] = "rebase"
                    else:
                        return

                apply = conf.get_action("updates.bootc.stage.rebase.apply")
                cancel = conf.get_action("updates.bootc.stage.rebase.cancel")
                branch = conf.get(
                    "updates.bootc.stage.rebase.branch", next(iter(self.branches))
                )

                version = "latest"
                if not self.t_data:
                    conf["updates.bootc.stage.rebase.version_error"] = _(
                        "Failed to load previous versions"
                    )
                else:
                    conf["updates.bootc.stage.rebase.version_error"] = None
                    if branch in self.t_data:
                        bdata = {k.replace(".", ""): k for k in self.t_data[branch]}
                        version = conf.get(
                            "updates.bootc.stage.rebase.version.value", "latest"
                        )
                        conf["updates.bootc.stage.rebase.version"] = None
                        conf["updates.bootc.stage.rebase.version"] = {
                            "options": {
                                "latest": "Latest",
                                **bdata,
                            },
                            "value": version if version in bdata else "latest",
                        }
                        # Readd . since config system does not support them
                        version = bdata.get(version, "latest")

                if cancel:
                    self._init(conf)
                elif apply:
                    if version == "latest":
                        version = branch

                    curr = get_ref_from_status(self.status)
                    next_ref = (
                        (curr[: curr.rindex(":")] if ":" in curr else curr)
                        + ":"
                        + version
                    )
                    if next_ref == curr:
                        self._init(conf)
                    else:
                        self.state = "loading_cancellable"
                        cmd = [BOOTC_PATH, "switch", next_ref]
                        if self.bootc_progress:
                            self.proc, self.progress = run_command_threaded_progress(
                                cmd, self.emit, version, self.progress_lock
                            )
                        else:
                            self.proc = run_command_threaded(cmd)
                        conf["updates.bootc.stage.mode"] = "loading_cancellable"
                        conf["updates.bootc.stage.loading_cancellable.progress"] = {
                            "text": _("Rebasing to "),
                            "unit": self.branches.get(version, version),
                            "value": None,
                        }

            # Wait for the subcommand to complete
            case "loading_cancellable":
                cancel = conf.get_action(
                    f"updates.bootc.stage.loading_cancellable.cancel"
                )
                if self.proc is None:
                    self._init(conf)
                elif exit := self.proc.poll() is not None:
                    if exit and self.updating:
                        logger.error(
                            f"Command failed with exit code {exit}. Fallback to rpm-ostree"
                        )
                        self.proc = run_command_threaded(RPM_OSTREE_UPDATE)
                        conf["updates.bootc.stage.loading_cancellable.progress"] = {
                            "text": _("Update error. Using alternative method... "),
                            "value": None,
                            "unit": None,
                        }

                        # Prevent fallback running forever
                        self.updating = False
                    else:
                        self._init(conf)
                        self.proc = None
                elif cancel:
                    logger.info("User cancelled update. Stopping...")
                    self.proc.send_signal(signal.SIGINT)
                    self.proc.wait()
                    self.proc = None
                    self._init(conf)
                elif self.progress:
                    with self.progress_lock:
                        conf["updates.bootc.stage.loading_cancellable.progress"] = (
                            self.progress
                        )
                        val = self.progress.get("value", None)
                        if val is not None:
                            try:
                                val = int(val)
                                conf["updates.bootc.steamos-update"] = f"{val}%"
                            except ValueError:
                                pass
            case "loading":
                if self.proc is None:
                    self._init(conf)
                elif self.proc.poll() is not None:
                    self._init(conf)
                    self.proc = None

    def close(self):
        if self.proc:
            self.proc.send_signal(signal.SIGINT)
            self.proc.wait()
            self.proc = None
        if self.t:
            if self.t.is_alive():
                self.t.join()
            self.t = None


def autodetect(existing: Sequence[HHDPlugin]) -> Sequence[HHDPlugin]:
    if len(existing):
        return existing

    if not BOOTC_ENABLED:
        return []

    if not shutil.which(BOOTC_PATH):
        logger.warning("Bootc is enabled but not found in path.")
        return []

    return [BootcPlugin()]
