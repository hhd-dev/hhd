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


TM = TouchScreenMatch

TOUCH_SCREEN_QUIRKS = {
    # Lenovo
    TM("83E1", name="Legion GO"): TQ(True, False, False),
    # MinisForum
    TM("V3", name="MinisForum V3"): TQ(False, True, False),
    # Steam deck
    TM("Galileo", name="Steam Deck OLED"): TQ(True, False, True),
    # GPD
    TM("G1618-04", vid=0x0416, pid=0x038F, name="GPD Win 4"): TQ(False, True, False),
    # Asus
    TM("RC71L", name="ROG Ally"): TQ(False, True, False),
    TM("RC72LA", name="ROG Ally X"): TQ(False, True, False),
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
