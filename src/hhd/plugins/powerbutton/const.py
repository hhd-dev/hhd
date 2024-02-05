from typing import Literal, NamedTuple, Sequence, TypedDict


class PowerButtonConfig(NamedTuple):
    device: str
    prod_name: str
    type: Literal["hold_emitted", "hold_isa"] = "hold_isa"
    phys: Sequence[str] = ["LNXPWRBN", "PNP0C0C"]
    hold_phys: Sequence[str] = ["phys-hhd-powerbutton", "isa0060"]
    hold_grab: bool = False
    hold_code: int = 125  # left meta


# POWER_BUTTON_NAMES = ["Power Button"]
# POWER_BUTTON_PHYS = ["LNXPWRBN", "PNP0C0C"]

PBC = PowerButtonConfig

SUPPORTED_DEVICES: Sequence[PowerButtonConfig] = [
    PBC("Legion Go", "83E1"),
    PBC("ROG Ally", "ROG Ally RC71L_RC71L"),
    PBC("ROG Ally", "ROG Ally RC71L"),
    PBC("GPT Win 4", "G1618-04"),
    PBC("GPD Win Mini", "G1617-01"),
    PBC("GPD Win Max 2 2023", "G1619-05"),
    # TODO: Remove these when correct behavior is verified
    # TODO: Fix isa handling to only work when only shift is active
    # PBC("AYANEO AIR Plus", "AIR Plus", type="hold_emitted"),
    # PBC("AYANEO 2", "AYANEO 2", type="hold_emitted"),
    # PBC("AYANEO GEEK", "GEEK", type="hold_emitted"),
    # PBC("AYANEO 2S", "AYANEO 2S", type="hold_emitted"),
    # PBC("AYANEO GEEK 1S", "GEEK 1S", type="hold_emitted"),
    # PBC("AYANEO AIR", "AIR", type="hold_emitted"),
    # PBC("AYANEO AIR Pro", "AIR Pro", type="hold_emitted"),
    PBC(
        "Steam Deck LCD",
        "Jupiter",
        type="hold_emitted",
        phys=["isa0060", "PNP0C0C", "LNXPWRBN"],
    ),
    PBC(
        "Steam Deck OLED",
        "Galileo",
        type="hold_emitted",
        phys=["isa0060", "PNP0C0C", "LNXPWRBN"],
    ),
    PBC(
        "AOKZOE A1",
        "AOKZOE A1 AR07",
        type="hold_emitted",
        phys=["LNXPWRBN"],
    ),
    PBC(
        "AOKZOE A1 Pro",
        "AOKZOE A1 Pro",
        type="hold_emitted",
        phys=["LNXPWRBN"],
    ),
    PBC(
        "ONEXPLAYER Mini Pro",
        "ONEXPLAYER Mini Pro",
        type="hold_emitted",
        phys=["LNXPWRBN"],
    ),
]

DEFAULT_DEVICE: PowerButtonConfig = PBC("uknown", "NA", "hold_emitted")


# Legion go
# At device with phys=isa0060/serio0/input0
#
# event at 1702329391.831152, code 04, type 04, val 219
# event at 1702329391.831152, code 125, type 01, val 01
# event at 1702329391.831152, code 00, type 00, val 00
# event at 1702329391.834208, code 04, type 04, val 103
# event at 1702329391.834208, code 00, type 00, val 00

# event at 1702329392.152298, code 04, type 04, val 219
# event at 1702329392.152298, code 125, type 01, val 00
# event at 1702329392.152298, code 00, type 00, val 00
# event at 1702329392.156347, code 04, type 04, val 103
# event at 1702329392.156347, code 00, type 00, val 00
