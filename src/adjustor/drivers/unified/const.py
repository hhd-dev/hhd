from typing import TypedDict

from hhd.utils import get_ac_status, get_ac_status_fn


ProfileUnits = dict[str, int]


class PowerProfileUnits(TypedDict):
    ac: ProfileUnits
    dc: ProfileUnits


def _profiles(low_power: int, balanced: int, performance: int) -> ProfileUnits:
    return {
        "low-power": low_power,
        "quiet": low_power,
        "balanced": balanced,
        "performance": performance,
    }


def _same_power_source(profile: ProfileUnits) -> PowerProfileUnits:
    return {"ac": profile, "dc": profile}


# AMD DPTCi profile values. The 25W, 28W, and 30W device classes use the
# same sustained profile limits; their different custom limits come from the
# kernel firmware-attributes interface.
DPTC_15W = _same_power_source(_profiles(5, 10, 15))
DPTC_18W = _same_power_source(_profiles(5, 12, 18))
DPTC_HANDHELD = _same_power_source(_profiles(8, 15, 25))
DPTC_AI_MAX = _same_power_source(_profiles(15, 25, 45))

# Lenovo platform profiles.
LEGION_GO = _same_power_source(_profiles(8, 15, 20))
LEGION_GO_S = _same_power_source(_profiles(8, 15, 25))
LEGION_GO_2: PowerProfileUnits = {
    "ac": _profiles(15, 25, 35),
    "dc": _profiles(8, 16, 20),
}

# ASUS platform profiles.
ROG_ALLY: PowerProfileUnits = {
    "ac": _profiles(10, 15, 30),
    "dc": _profiles(10, 15, 25),
}
ROG_ALLY_X: PowerProfileUnits = {
    "ac": _profiles(13, 17, 30),
    "dc": _profiles(13, 17, 25),
}
ROG_XBOX_ALLY = _same_power_source(_profiles(6, 15, 20))
ROG_XBOX_ALLY_X = _same_power_source(_profiles(13, 17, 35))
ROG_FLOW_Z13: PowerProfileUnits = {
    "ac": _profiles(40, 45, 65),
    "dc": _profiles(40, 45, 54),
}


# Prefer board names. Entries here mirror the DMI_BOARD_NAME matches in the
# amd-dptc kernel driver, with ASUS board identifiers included for future use.
BOARD_PROFILE_DATA: dict[str, PowerProfileUnits] = {
    # ASUS
    "RC71L": ROG_ALLY,
    "RC72L": ROG_ALLY_X,
    "RC73Y": ROG_XBOX_ALLY,
    "RC73X": ROG_XBOX_ALLY_X,
    "GZ302": ROG_FLOW_Z13,
    # Minisforum
    "HPPAC": DPTC_HANDHELD,
    # OrangePi
    "NEO-01": DPTC_HANDHELD,
    # AOKZOE
    "AOKZOE A1 AR07": DPTC_HANDHELD,
    "AOKZOE A1 Pro": DPTC_HANDHELD,
    "AOKZOE A1X": DPTC_HANDHELD,
    "AOKZOE A2 Pro": DPTC_HANDHELD,
    # OneXPlayer
    "ONEXPLAYER F1 EVA-02": DPTC_HANDHELD,
    "ONEXPLAYER F1Pro": DPTC_HANDHELD,
    "ONEXPLAYER 2": DPTC_HANDHELD,
    "ONEXPLAYER X1 A": DPTC_HANDHELD,
    "ONEXPLAYER X1z": DPTC_HANDHELD,
    "ONEXPLAYER X1Pro": DPTC_HANDHELD,
    "ONEXPLAYER X2Mini PRO": DPTC_AI_MAX,
    "ONEXPLAYER G1 A": DPTC_HANDHELD,
    # AYANEO
    "AIR Plus": DPTC_18W,
    "AIR Pro": DPTC_18W,
    "AIR 1S": DPTC_HANDHELD,
    "NEXT Advance": DPTC_HANDHELD,
    "NEXT Lite": DPTC_HANDHELD,
    "NEXT Pro": DPTC_HANDHELD,
    "AYANEO KUN": DPTC_HANDHELD,
    "AYANEO 2": DPTC_HANDHELD,
    "AYANEO 3": DPTC_HANDHELD,
    "FLIP": DPTC_HANDHELD,
    "GEEK": DPTC_HANDHELD,
    "SLIDE": DPTC_HANDHELD,
    "NEXT": DPTC_HANDHELD,
    "KUN": DPTC_HANDHELD,
    "AIR": DPTC_15W,
}


# Product-name matches are limited to kernel quirks and devices whose board
# name is not a stable model identity (notably Lenovo's shared board name).
PRODUCT_PROFILE_DATA: dict[str, PowerProfileUnits] = {
    # Lenovo
    "83E1": LEGION_GO,
    "83L3": LEGION_GO_S,
    "83N6": LEGION_GO_S,
    "83Q2": LEGION_GO_S,
    "83Q3": LEGION_GO_S,
    "83N0": LEGION_GO_2,
    "83N1": LEGION_GO_2,
    # GPD
    "G1617-01": DPTC_HANDHELD,
    "G1617-02-L": DPTC_HANDHELD,
    "G1617-02": DPTC_HANDHELD,
    "G1618-04": DPTC_HANDHELD,
    "G1618-05": DPTC_AI_MAX,
    "G1619-04": DPTC_HANDHELD,
    "G1619-05": DPTC_HANDHELD,
    "G1622-01-L": DPTC_HANDHELD,
    "G1622-01": DPTC_HANDHELD,
    "G1628-04-L": DPTC_HANDHELD,
    "G1628-04": DPTC_HANDHELD,
    # Other kernel product-name quirks
    "Loki Max": DPTC_HANDHELD,
    "Zeenix Pro": DPTC_HANDHELD,
    "SuiPlay0X1": DPTC_HANDHELD,
}


def _read_dmi(name: str) -> str | None:
    try:
        with open(f"/sys/devices/virtual/dmi/id/{name}") as f:
            return f.read().strip()
    except Exception:
        return None


def _match_identity(
    identity: str | None, data: dict[str, PowerProfileUnits]
) -> PowerProfileUnits | None:
    if not identity:
        return None

    if identity in data:
        return data[identity]

    for match, profiles in data.items():
        if match in identity:
            return profiles

    return None


def get_profile_units() -> ProfileUnits | None:
    profiles = _match_identity(_read_dmi("board_name"), BOARD_PROFILE_DATA)
    if profiles is None:
        profiles = _match_identity(
            _read_dmi("product_name"), PRODUCT_PROFILE_DATA
        )
    if profiles is None:
        return None

    # Default to the AC values when the power source can not be determined.
    power_source = "dc" if get_ac_status(get_ac_status_fn()) is False else "ac"
    return profiles[power_source]
