from typing import Literal, NamedTuple, Sequence, TypedDict


class PowerButtonConfig(NamedTuple):
    device: str
    prod_name: str
    type: Literal["hold_emitted", "hold_isa"] = "hold_isa"
    phys: Sequence[str] = ["LNXPWRBN", "PNP0C0C"]
    hold_phys: Sequence[str] = ["phys-hhd-powerbutton", "isa0060"]
    hold_grab: bool = False
    hold_code: int = 125  # left meta
    unsupported: bool = False


# POWER_BUTTON_NAMES = ["Power Button"]
# POWER_BUTTON_PHYS = ["LNXPWRBN", "PNP0C0C"]

PBC = PowerButtonConfig

SUPPORTED_DEVICES: Sequence[PowerButtonConfig] = [
    PBC("Legion Go", "83E1"),
    PBC("ROG Ally", "ROG Ally RC71L_Action"),
    PBC("ROG Ally", "ROG Ally RC71L_RC71L"),
    PBC("ROG Ally", "ROG Ally RC71L"),
    PBC("ROG Ally X", "ROG Ally X RC72LA"),
    PBC("GPT Win 4", "G1618-04"),
    PBC("GPD Win Mini", "G1617-01"),
    PBC("GPD Win Max 2 2023", "G1619-05"),
    PBC("OrangePi G1621-02/G1621-02", "G1621-02"),
    PBC("OrangePi NEO-01/NEO-01", "NEO-01"),
    # breaks volume buttons, use the valve original script and hope steam inhibits systemd
    # PBC(
    #     "Steam Deck LCD",
    #     "Jupiter",
    #     type="hold_emitted",
    #     phys=["isa0060", "PNP0C0C", "LNXPWRBN"],
    # ),
    # PBC(
    #     "Steam Deck OLED",
    #     "Galileo",
    #     type="hold_emitted",
    #     phys=["isa0060", "PNP0C0C", "LNXPWRBN"],
    # ),
    PBC(
        "AOKZOE A1",
        "AOKZOE A1 AR07",
        type="hold_emitted",
        phys=["LNXPWRBN", "PNP0C0C"],
    ),
    PBC(
        "AOKZOE A1 Pro",
        "AOKZOE A1 Pro",
        type="hold_emitted",
        phys=["LNXPWRBN", "PNP0C0C"],
    ),
    PBC(
        "ONEXPLAYER Mini Pro",
        "ONEXPLAYER Mini Pro",
        type="hold_emitted",
        phys=["LNXPWRBN", "PNP0C0C"],
    ),
]


def get_config() -> PowerButtonConfig:
    with open("/sys/devices/virtual/dmi/id/product_name") as f:
        prod = f.read().strip()

    try:
        with open("/sys/devices/virtual/dmi/id/sys_vendor") as f:
            sys = f.read().strip()
    except Exception:
        sys = None

    for d in SUPPORTED_DEVICES:
        if d.prod_name in prod:
            return d

    if "ONEXPLAYER" in prod or "AOKZOE" in prod:
        return PBC(prod, prod, type="hold_emitted", phys=["LNXPWRBN"])

    if sys == "AYA" or sys == "AYANEO" or sys == "AYN":
        # TODO: Fix isa handling to only work when only shift is active
        return PBC(prod, prod, type="hold_emitted")

    return PBC("uknown", "NA", "hold_emitted", unsupported=True)


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
