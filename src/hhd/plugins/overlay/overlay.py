import os
import shutil
import subprocess

from hhd.plugins import Context
from hhd.utils import expanduser


def find_overlay_exe(ctx: Context):
    INSTALLED_PATHS = ["hhd-ui.AppImage", "hhd-ui-dbg", "hhd-ui"]

    usr = os.environ.get("HHD_OVERLAY")
    if usr:
        if os.path.exists(usr):
            return usr
        INSTALLED_PATHS.insert(0, usr)

    # FIXME: Potential priviledge escalation attack!
    # Runs as the user in `inject_overlay`, so this should
    # not be the case. Will still be executed.
    for fn in INSTALLED_PATHS:
        local = shutil.which(fn, path=expanduser("~/.local/bin", ctx))
        if local:
            return local

    for fn in INSTALLED_PATHS:
        system = shutil.which(fn)
        if system:
            return system


def inject_overlay(fn: str, display: str, ctx: Context):
    out = subprocess.Popen(
        [fn],
        env={"HOME": expanduser("~", ctx), "DISPLAY": display, "STEAM_OVERLAY": "1"},
        text=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        preexec_fn=lambda: os.setpgrp(), # allow closing the overlay smoothly
        user=ctx.euid,
        group=ctx.egid,
    )
    return out


def launch_overlay_de(fn: str, display: str, auth: str, ctx: Context):
    out = subprocess.Popen(
        [fn],
        env={
            "HOME": expanduser("~", ctx),
            "XAUTHORITY": auth,
            "DISPLAY": display,
            "HHD_MANAGED": "1",
        },
        text=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        user=ctx.euid,
        group=ctx.egid,
    )
    return out


def get_overlay_version(fn: str, ctx: Context):
    return subprocess.run(
        [fn, "--version"],
        env={"HOME": expanduser("~", ctx)},
        text=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        user=ctx.euid,
        group=ctx.egid,
        timeout=5,
    ).stdout.strip()
