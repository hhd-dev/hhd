from typing import NamedTuple


class TouchScreenQuirk(NamedTuple):
    portrait: bool
    flip_x: bool  # Left <-> Right
    flip_y: bool  # Top <-> Bottom


TQ = TouchScreenQuirk


class TouchScreenMatch(NamedTuple):
    dmi: str | None = None
    vid: int | None = None
    pid: int | None = None
    name: str | None = None

DEFAULT_LANDSCAPE = TQ(False, True, False)

TM = TouchScreenMatch

TOUCH_SCREEN_QUIRKS = {
    # Lenovo
    TM("83E1", name="Legion GO"): TQ(True, False, False),
    # MinisForum
    TM("V3", name="MinisForum V3"): DEFAULT_LANDSCAPE,
    # Steam deck
    TM("Jupiter", name="Steam Deck LCD"): TQ(True, True, True),
    TM("Galileo", name="Steam Deck OLED"): TQ(True, True, True),
    # GPD
    TM("G1618-04", name="GPD Win 4"): DEFAULT_LANDSCAPE,  # 2023: 0x0416:0x038F
    TM("G1619-04", name="GPD Win Max 2 (04)"): DEFAULT_LANDSCAPE,  # 2023: 27C6:0113
    TM("G1619-05", name="GPD Win Max 2 (05)"): DEFAULT_LANDSCAPE,
    # Asus
    TM("RC71L", name="ROG Ally"): DEFAULT_LANDSCAPE,
    TM("RC72LA", name="ROG Ally X"): DEFAULT_LANDSCAPE,
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
