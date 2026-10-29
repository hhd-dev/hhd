import logging
import os
import shutil
import stat
import subprocess

from hhd.plugins import Context, get_gid
from hhd.utils import expanduser

logger = logging.getLogger(__name__)


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
        env={
            "HOME": expanduser("~", uid),
            "DISPLAY": display,
            "STEAM_OVERLAY": "1",
            # The AppImage runtime needs PATH to find fusermount.
            "PATH": "/usr/bin:/bin",
        },
        text=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        # hhd-ui is commonly an AppImage. Keep Electron and all of its helper
        # processes in a separate process group so they can be stopped before
        # the AppImage mount is torn down.
        start_new_session=True,
        user=uid,
        group=get_gid(uid),
    )
    return out


def find_wayland_socket(uid: int):
    """Returns (runtime dir, socket name) of a wayland compositor of `uid`."""
    # TODO: Fix hardcoding runtime dir (same as find_x11_auth)
    runtime_dir = f"/run/user/{uid}"
    try:
        files = sorted(os.listdir(runtime_dir))
    except OSError:
        return None

    for fn in files:
        # gamescope uses gamescope-N, which is not matched here on purpose
        if not fn.startswith("wayland-") or fn.endswith(".lock"):
            continue
        try:
            if stat.S_ISSOCK(os.stat(os.path.join(runtime_dir, fn)).st_mode):
                return runtime_dir, fn
        except OSError:
            continue
    return None


def launch_overlay_de(fn: str, display: str, auth: str | None, uid: int, gid: int):
    env = {
        "HOME": expanduser("~", uid),
        "XAUTHORITY": auth or "",
        "DISPLAY": display,
        "HHD_MANAGED": "1",
        # The AppImage runtime needs PATH to find fusermount.
        "PATH": "/usr/bin:/bin",
    }

    # By default electron gets only an X11 display, so it runs under XWayland
    # (blurry with fractional scaling). With HHD_OVERLAY_WAYLAND=1, also hand
    # it the user's wayland socket and ask it to use that. DISPLAY stays set,
    # so it still falls back to X11 when no compositor socket is found.
    if os.environ.get("HHD_OVERLAY_WAYLAND") == "1":
        sock = find_wayland_socket(uid)
        if sock:
            env["XDG_RUNTIME_DIR"], env["WAYLAND_DISPLAY"] = sock
            # electron ignores the hint unless the session type says wayland
            env["XDG_SESSION_TYPE"] = "wayland"
            env["ELECTRON_OZONE_PLATFORM_HINT"] = "wayland"
            logger.info(f"Launching hhd-ui on wayland socket '{sock[1]}'.")
        else:
            logger.warning(
                "HHD_OVERLAY_WAYLAND is set but no wayland socket was found, "
                "falling back to X11."
            )

    out = subprocess.Popen(
        [fn],
        env=env,
        text=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
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
