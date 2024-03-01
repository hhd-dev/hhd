import os
import shutil

from hhd.plugins import Context
from hhd.utils import expanduser
import subprocess


def find_overlay_exe():
    INSTALLED_PATHS = ["hhd-ui-dbg", "hhd-ui"]

    for fn in INSTALLED_PATHS:
        if shutil.which(fn):
            return fn


def inject_overlay(fn: str, display: str, ctx: Context):
    out = subprocess.Popen(
        [fn],
        env={"HOME": expanduser("~", ctx), "DISPLAY": display, "STEAM_OVERLAY": "1"},
        text=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        user=ctx.euid,
        group=ctx.egid,
    )
    return out
