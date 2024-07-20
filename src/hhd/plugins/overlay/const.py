from typing import NamedTuple


class TouchScreenQuirk(NamedTuple):
    portrait: bool
    flip_x: bool
    flip_y: bool


TQ = TouchScreenQuirk


class TouchScreenMatch(NamedTuple):
    dmi: str | None = None
    vid: int | None = None
    pid: int | None = None
    name: str | None = None


TM = TouchScreenMatch

TOUCH_SCREEN_QUIRKS = {
    TM("83E1", name="Legion GO"): TQ(True, False, False),
    TM("V3", name="MinisForum V3"): TQ(True, True, False),
}


def get_touchscreen_quirk(vid=None, pid=None):
    try:
        with open("/sys/class/dmi/id/product_name") as f:
            dmi = f.read().strip()
    except Exception:
        return None, None

    for match, quirk in TOUCH_SCREEN_QUIRKS.items():
        if match.dmi and match.dmi not in dmi:
            continue
        if match.vid and match.vid != vid:
            continue
        if match.pid and match.pid != pid:
            continue

        return (
            quirk,
            match.name,
        )

    return None, None


def get_system_info():
    try:
        with open("/sys/class/dmi/id/product_name") as f:
            dmi = f.read().strip()
    except Exception:
        dmi = ""

    try:
        with open("/sys/class/dmi/id/sys_vendor") as f:
            vendor = f.read().strip()
    except Exception:
        vendor = ""

    return vendor, dmi
