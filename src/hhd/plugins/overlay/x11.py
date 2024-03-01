import logging
import subprocess
from typing import Sequence

from Xlib import Xatom, display, error

logger = logging.getLogger(__name__)

X11_DIR = b"/tmp/.X11-unix/"


def get_gamescope_displays():
    """Returns X11 UNIX sockets from gamescope opened under /tmp"""
    files = subprocess.run(["lsof", "-c", "gamescope-wl", "-Fn"], capture_output=True)
    out = []
    for ln in files.stdout.splitlines():
        if len(ln) < 1:
            continue
        ln = ln[1:]

        if not ln.startswith(X11_DIR):
            continue

        fn = ln.split(b" ")[0]
        disp = ":" + fn[len(X11_DIR) + 1 :].decode()
        out.append(disp)
    return out


def get_overlay_display(displays: Sequence[str]):
    """Probes the provided gamescope displays to find the overlay one."""
    for disp in displays:
        d = display.Display(disp)

        atoms = [d.get_atom_name(v) for v in d.screen().root.list_properties()]
        if "GAMESCOPE_FOCUSED_WINDOW" in atoms:
            return d, disp

        d.close()


def find_win(display: display.Display, win: list[str]):
    n = display.get_atom("WM_CLASS")
    for w in display.screen().root.query_tree().children:
        v = w.get_property(n, Xatom.STRING, 0, 50)
        if not v:
            continue
        if not v.value:
            continue

        classes = [c.decode() for c in v.value.split(b"\00") if c]
        found = True
        for val in win:
            if val not in classes:
                found = False

        if found:
            return w


def find_hhd(display: display.Display):
    return find_win(display, ["dev.hhd.hhd-ui"])


def find_steam(display: display.Display):
    return find_win(display, ["steamwebhelper", "steam"])


def print_data(display: display.Display):
    for w in (find_hhd(display), find_steam(display), display.screen().root):
        if not w:
            continue
        for p in w.list_properties():
            req = w.get_property(p, Xatom.CARDINAL, 0, 100)
            if req:
                v = list(req.value) if req.value else None
            else:
                v = None
            print(f"{p:4d}-{display.get_atom_name(p):>40s}: {v}")
        print()


def print_debug(display: display.Display):
    d = display
    r = display.screen().root

    print("ATOMS:")
    for v in r.list_properties():
        print(f"{v: 4d}: {d.get_atom_name(v)}")

    print()
    print("WINDOWS:")
    for i, w in enumerate(r.query_tree().children):
        print(f"{i:02d}", end="")
        for p in w.list_properties():
            n = d.get_atom_name(p)
            if "WM_NAME" == n:
                print(
                    f" {w.get_property(p, Xatom.STRING, 0, 100).value.decode()}", end=""
                )
        print(f":", end="")
        for p in w.list_properties():
            n = d.get_atom_name(p)
            if "STEAM" in n or "GAMESCOPE" in n:
                print(
                    f" {n}: {list(w.get_property(p, Xatom.CARDINAL, 0, 15).value)},",
                    end="",
                )

        print()
        for p in w.list_properties():
            n = d.get_atom_name(p)
            if "STEAM" not in n and "GAMESCOPE" not in n:
                print(
                    f"- {n}: {list(w.get_property(p, Xatom.CARDINAL, 0, 15).value) or w.get_property(p, Xatom.STRING, 0, 15).value},",
                )


def prepare_hhd(display, hhd):
    hhd.change_property(display.get_atom("STEAM_GAME"), Xatom.CARDINAL, 32, [5335])
    hhd.change_property(display.get_atom("STEAM_NOTIFICATION"), Xatom.CARDINAL, 32, [0])
    hhd.change_property(display.get_atom("STEAM_BIGPICTURE"), Xatom.CARDINAL, 32, [1])


def show_hhd(display, hhd, steam):
    stat_focus = display.get_atom("STEAM_INPUT_FOCUS")
    stat_overlay = display.get_atom("STEAM_OVERLAY")

    old = (
        steam.get_property(stat_focus, Xatom.CARDINAL, 0, 15),
        steam.get_property(stat_overlay, Xatom.CARDINAL, 0, 15),
    )

    hhd.change_property(stat_focus, Xatom.CARDINAL, 32, [1])
    hhd.change_property(stat_overlay, Xatom.CARDINAL, 32, [1])
    steam.change_property(stat_focus, Xatom.CARDINAL, 32, [0])
    steam.change_property(stat_overlay, Xatom.CARDINAL, 32, [0])

    # Force the values to refresh
    hhd.get_property(stat_focus, Xatom.CARDINAL, 0, 5)
    hhd.get_property(stat_overlay, Xatom.CARDINAL, 0, 5)
    steam.get_property(stat_focus, Xatom.CARDINAL, 0, 5)
    steam.get_property(stat_overlay, Xatom.CARDINAL, 0, 5)

    return old


def is_steam_shown(display, steam):
    stat_focus = display.get_atom("STEAM_INPUT_FOCUS")
    stat_overlay = display.get_atom("STEAM_OVERLAY")
    try:
        v1 = steam.get_property(stat_focus, Xatom.CARDINAL, 0, 5).value[0]
        v2 = steam.get_property(stat_overlay, Xatom.CARDINAL, 0, 5).value[0]
        return bool(v1 or v2)
    except Exception as e:
        logger.warning(f"Could not read steam overlay status with error:\n{e}")
        return False


def hide_hhd(display, hhd, steam, old):
    stat_focus = display.get_atom("STEAM_INPUT_FOCUS")
    stat_overlay = display.get_atom("STEAM_OVERLAY")

    # Set values
    hhd.change_property(stat_focus, Xatom.CARDINAL, 32, [0])
    hhd.change_property(stat_overlay, Xatom.CARDINAL, 32, [0])
    # Refresh values
    hhd.get_property(stat_focus, Xatom.CARDINAL, 0, 5)
    hhd.get_property(stat_overlay, Xatom.CARDINAL, 0, 5)

    # Restore steam
    if not old:
        return

    if old[0]:
        steam.change_property(stat_focus, Xatom.CARDINAL, 32, old[0].value)
        steam.get_property(stat_focus, Xatom.CARDINAL, 0, 5)
    if old[1]:
        steam.change_property(stat_overlay, Xatom.CARDINAL, 32, old[1].value)
        steam.get_property(stat_overlay, Xatom.CARDINAL, 0, 5)
