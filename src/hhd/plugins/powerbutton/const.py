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
    PBC(
        "Legion Go",
        "83E1",
    ),
    PBC(
        "ROG Ally",
        "ROG Ally RC71L_RC71L",
    ),
]

DEFAULT_DEVICE: PowerButtonConfig = PBC(
    "uknown",
    "NA",
)


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
