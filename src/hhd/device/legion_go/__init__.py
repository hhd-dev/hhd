from typing import Sequence

from hhd.plugins import (
    HHDPlugin,
)

from .tablet import LegionGoControllersPlugin

LEGION_CONFS = {
    "83E1": {
        "name": "Legion Go (1st Gen)",
        "dual": True,
    },
    "83L3": {
        "name": "Legion Go S",
        "dual": False,
    },
}


def autodetect(existing: Sequence[HHDPlugin]) -> Sequence[HHDPlugin]:
    if len(existing):
        return existing

    # Match just product number, should be enough for now
    with open("/sys/devices/virtual/dmi/id/product_name") as f:
        dmi = f.read().strip()

    if dmi not in LEGION_CONFS:
        return []

    return [LegionGoControllersPlugin(dconf=LEGION_CONFS[dmi])]
