import os
import shutil
import subprocess

from hhd.plugins import Context, get_gid
from hhd.utils import expanduser


def find_overlay_exe(uid: Context | int | None = None) -> str | None:
    INSTALLED_PATHS = ["hhd-ui.AppImage", "hhd-ui-dbg", "hhd-ui"]

    usr = os.environ.get("HHD_OVERLAY")
    if usr:
        if os.path.exists(usr):
            return usr
        INSTALLED_PATHS.insert(0, usr)

    # FIXME: Potential priviledge escalation attack!
    # Runs as the user in `inject_overlay`, so this should
    # not be the case. Will still be executed.
    if uid is not None:
        for fn in INSTALLED_PATHS:
            local = shutil.which(fn, path=expanduser("~/.local/bin", uid))
            if local:
                return local

    for fn in INSTALLED_PATHS:
        system = shutil.which(fn)
        if system:
            return system


def inject_overlay(fn: str, display: str, uid: int):
    out = subprocess.Popen(
        [fn],
        env={"HOME": expanduser("~", uid), "DISPLAY": display, "STEAM_OVERLAY": "1"},
        text=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        preexec_fn=lambda: os.setpgrp(), # allow closing the overlay smoothly
        user=uid,
        group=get_gid(uid),
    )
    return out


def launch_overlay_de(fn: str, display: str, auth: str | None, uid: int, gid: int):
    out = subprocess.Popen(
        [fn],
        env={
            "HOME": expanduser("~", uid),
            "XAUTHORITY": auth or "",
            "DISPLAY": display,
            "HHD_MANAGED": "1",
        },
        text=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        user=uid,
        group=gid,
    )
    return out


def get_overlay_version(fn: str):
    return subprocess.run(
        [fn, "--version"],
        text=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=5,
    ).stdout.strip()
