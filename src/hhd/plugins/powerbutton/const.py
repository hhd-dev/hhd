from typing import Literal, NamedTuple, Sequence, TypedDict


class PowerButtonConfig(NamedTuple):
    device: str
    type: Literal["hold_emitted", "hold_isa"]
    prod_name: str
    phys: str
    hold_phys: str | None = None
    hold_grab: bool | None = None
    # ev.type, ev.code, ev.value pairs
    hold_events: Sequence[tuple[int, int, int]] | None = None


# POWER_BUTTON_NAMES = ["Power Button"]
# POWER_BUTTON_PHYS = ["LNXPWRBN", "PNP0C0C"]

PBC = PowerButtonConfig

SUPPORTED_DEVICES: Sequence[PowerButtonConfig] = [
    PBC(
        "Legion Go",
        "hold_isa",
        "83E1",
        "PNP0C0C",
        "isa0060",
        False,
        [(4, 4, 219), (1, 125, 1), (0, 0, 0)],
    )
]

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
